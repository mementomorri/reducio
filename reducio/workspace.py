"""Workspace facade — in-process repo tools."""

from __future__ import annotations

import hashlib
from pathlib import Path

from reducio import parse, repo
from reducio.git_safety import GitSafety
from reducio.models import AppConfig, ComplexityMetrics, FileChange, FileInfo, Symbol
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
        self._resolve_path(path)
        file = repo._read_one(self.root, self.root / path)
        if file.error:
            raise ValueError(file.error)
        return file

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

    def apply_changes_safe(
        self, changes: list[FileChange], run_tests: bool = False, validate_after=None
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
            proposed: dict[str, bytes] = {}
            originals = {}
            for change in changes:
                relative = change.path
                path = safe_target(self.root, relative)
                key = str(path.resolve())
                if key in originals:
                    raise ValueError("Duplicate change destination")
                original = path.read_bytes() if path.exists() else None
                if change.creates_file:
                    if original is not None or change.original:
                        raise ValueError(f"Refusing to create over existing file: {relative}")
                elif original is None or original != change.original.encode(change.encoding):
                    raise ValueError(f"Original bytes differ: {relative}; regenerate the plan")
                content = change.modified.encode(change.encoding)
                if relative.lower().endswith(".py"):
                    compile(content, relative, "exec")
                originals[key] = original
                proposed[relative] = content
            snapshot = FileSnapshot(self.root, list(proposed))
            outcome["backup_location"] = str(snapshot.directory)
            for relative in proposed:
                original_bytes = originals[str((self.root / relative).resolve())]
                expected = (
                    hashlib.sha256(original_bytes).hexdigest()
                    if original_bytes is not None
                    else None
                )
                if snapshot.records[relative]["before"] != expected:
                    raise ValueError(f"Target changed concurrently: {relative}")
            for relative, content in proposed.items():
                snapshot.write(relative, content)
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
