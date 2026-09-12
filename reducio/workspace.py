"""Workspace facade — in-process repo tools."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from reducio import diff as diff_mod
from reducio import parse, repo
from reducio.git_safety import GitSafety
from reducio.models import AppConfig, ComplexityMetrics, FileInfo, Symbol
from reducio.runner import ProjectRunner


class PathEscapeError(ValueError):
    pass


class Workspace:
    def __init__(self, root_dir: str, cfg: AppConfig | None = None):
        self.root = Path(root_dir).resolve()
        self.cfg = cfg or AppConfig()
        self._git = GitSafety(str(self.root))
        self._runner = ProjectRunner(str(self.root), self.cfg)

    def _resolve_path(self, path: str) -> Path:
        full = (self.root / path).resolve()
        try:
            full.relative_to(self.root)
        except ValueError as e:
            raise PathEscapeError(f"path escapes workspace: {path}") from e
        return full

    def list_files(self) -> list[FileInfo]:
        return repo.walk(
            str(self.root),
            self.cfg.exclude_patterns,
            self.cfg.include_patterns,
        )

    def read_file(self, path: str) -> FileInfo:
        full = self._resolve_path(path)
        content = full.read_text(encoding="utf-8", errors="replace")
        rel = str(full.relative_to(self.root))
        h = hashlib.sha256(content.encode()).hexdigest()
        return FileInfo(path=rel, content=content, hash=h)

    def get_symbols(self, path: str, content: str | None = None) -> list[Symbol]:
        if content is None:
            content = self.read_file(path).content
        lang = repo.detect_language(path)
        symbols = parse.get_symbols(content, path, lang)
        for s in symbols:
            if not s.file:
                s.file = path
        return symbols

    def get_complexity(self, path: str, content: str | None = None) -> ComplexityMetrics:
        if content is None:
            content = self.read_file(path).content
        return parse.get_complexity(content)

    def apply_diff(self, path: str, diff_text: str) -> dict:
        result = self.apply_changes_safe([(path, diff_text)])
        if not result["success"]:
            raise diff_mod.DiffError(result["error"])
        return {**result, "path": path}

    def _invalid_python(self, changes: list[tuple[str, str]]) -> str | None:
        """Return the first changed .py file that no longer parses, else None."""
        seen: set[str] = set()
        for path, _ in changes:
            if path in seen or not path.endswith(".py"):
                continue
            seen.add(path)
            full = self._resolve_path(path)
            if not full.exists():
                continue
            try:
                ast.parse(full.read_text(encoding="utf-8"))
            except SyntaxError as e:
                return f"{path}: {e}"
        return None

    def apply_changes_safe(
        self, changes: list[tuple[str, str]], run_tests: bool = False, validate_after=None
    ) -> dict:
        """Apply scoped changes with verified recovery; never mutate Git HEAD/index."""
        from reducio.recovery import FileSnapshot, safe_target

        outcome = {
            "success": False,
            "tests_passed": False,
            "test_status": "not_run",
            "recovery_status": "not_needed",
            "recovery_errors": [],
            "applied": 0,
        }
        if not changes:
            return {**outcome, "success": True}
        snapshot = None
        try:
            # Simulate every hunk before writing anything, including repeated paths.
            proposed: dict[str, str] = {}
            originals = {}
            for relative, diff_text in changes:
                path = safe_target(self.root, relative)
                original = proposed.get(relative)
                if original is None:
                    originals[relative] = path.read_bytes() if path.exists() else None
                    original = (originals[relative] or b"").decode("utf-8")
                if diff_text.lstrip().startswith("--- /dev/null") and (
                    path.exists() or relative in proposed
                ):
                    raise ValueError(f"refusing to create over existing file: {relative}")
                proposed[relative] = diff_mod.apply_unified_diff(original, diff_text)
            snapshot = FileSnapshot(self.root, list(proposed))
            outcome["backup_location"] = str(snapshot.directory)
            for relative, original_bytes in originals.items():
                expected = (
                    hashlib.sha256(original_bytes).hexdigest()
                    if original_bytes is not None
                    else None
                )
                if snapshot.records[relative]["before"] != expected:
                    raise ValueError(f"Target changed concurrently: {relative}")
            for relative, content in proposed.items():
                snapshot.write(relative, content.encode("utf-8"))
            if broken := self._invalid_python(changes):
                raise ValueError(f"apply produced invalid Python: {broken}")
            if validate_after is not None:
                validate_after()
            if run_tests:
                outcome["test_status"] = "error"
                result = self._runner.run_tests()
                outcome.update(
                    test_status=result.status,
                    test_output=result.output,
                    test_command=result.command,
                    test_count=result.count,
                )
                if not result.success:
                    raise ValueError("Requested tests failed or could not run")
            if validate_after is not None:
                validate_after()
            snapshot.complete()
            outcome.update(
                success=True, applied=len(proposed), tests_passed=outcome["test_status"] == "passed"
            )
        except (Exception, KeyboardInterrupt) as error:
            outcome["error"] = (
                str(error)
                if isinstance(error, ValueError)
                else "Application interrupted or validation failed"
            )
            if snapshot is not None:
                errors = snapshot.restore()
                outcome.update(
                    recovery_errors=errors,
                    recovery_status="failed" if errors else "restored",
                    rolled_back=not errors,
                )
        outcome["tests_passed"] = outcome["test_status"] == "passed"
        return outcome

    def run_tests(self) -> dict:
        r = self._runner.run_tests()
        return {
            "success": r.success,
            "output": r.output,
            "command": r.command,
            "exit_code": r.exit_code,
            "status": r.status,
            "count": r.count,
        }

    def is_git_clean(self) -> bool:
        return self._git.is_clean()
