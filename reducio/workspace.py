"""Workspace facade — in-process repo tools."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from reducio import diff as diff_mod
from reducio import parse, repo
from reducio.git_safety import GitError, GitSafety
from reducio.models import AppConfig, ComplexityMetrics, FileChange, FileInfo, Symbol
from reducio.runner import ProjectRunner


class PathEscapeError(ValueError):
    pass


class Workspace:
    def __init__(self, root_dir: str, cfg: AppConfig | None = None):
        self.root = Path(root_dir).resolve()
        self.cfg = cfg or AppConfig()
        self._git = GitSafety(str(self.root))
        self._runner = ProjectRunner(str(self.root))

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
        full = self._resolve_path(path)
        if diff_text.lstrip().startswith("--- /dev/null"):
            # A create diff (empty original) must make a NEW file. Merging it into an
            # existing one would prepend the new content in front of the old file.
            if full.exists():
                raise diff_mod.DiffError(f"refusing to create over existing file: {path}")
            new_content = diff_mod.apply_unified_diff("", diff_text)
        else:
            original = full.read_text(encoding="utf-8") if full.exists() else ""
            new_content = diff_mod.apply_unified_diff(original, diff_text)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(new_content, encoding="utf-8")
        rel = str(full.relative_to(self.root))
        return {"success": True, "path": rel}

    def _safe_rollback(self, checkpoint: str | None, snapshot: dict[str, str | None]) -> None:
        if checkpoint:
            try:
                self._git.rollback()
            except GitError:
                pass
            return
        # No git checkpoint (non-git target): best-effort restore of pre-apply contents,
        # so the all-or-nothing guarantee holds even without git.
        for path, content in snapshot.items():
            full = self._resolve_path(path)
            if content is None:
                full.unlink(missing_ok=True)
            else:
                full.write_text(content, encoding="utf-8")

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
        self,
        changes: list[tuple[str, str]],
        run_tests: bool = True,
    ) -> dict:
        """Apply multiple diffs atomically; roll the whole batch back on any failure."""
        if not changes:
            return {"success": True, "applied": 0}
        checkpoint = None
        snapshot: dict[str, str | None] = {}
        if self._git.is_repo():
            try:
                checkpoint = self._git.create_checkpoint("reducio checkpoint before plan")
            except GitError as e:
                return {"success": False, "error": str(e), "applied": 0}
        else:
            for path, _ in changes:
                if path in snapshot:
                    continue
                full = self._resolve_path(path)
                snapshot[path] = full.read_text(encoding="utf-8") if full.exists() else None
        reverted = bool(checkpoint) or bool(snapshot)
        for path, diff_text in changes:
            try:
                self.apply_diff(path, diff_text)
            except Exception as e:
                self._safe_rollback(checkpoint, snapshot)
                return {
                    "success": False,
                    "error": str(e),
                    "path": path,
                    "rolled_back": reverted,
                    "applied": 0,
                }
        # Post-apply sanity: never leave (or commit) syntactically broken Python.
        broken = self._invalid_python(changes)
        if broken:
            self._safe_rollback(checkpoint, snapshot)
            return {
                "success": False,
                "error": f"apply produced invalid Python: {broken}",
                "rolled_back": reverted,
                "applied": 0,
            }
        if run_tests:
            result = self._runner.run_tests()
            if not result.success:
                self._safe_rollback(checkpoint, snapshot)
                return {
                    "success": False,
                    "tests_passed": False,
                    "rolled_back": reverted,
                    "test_output": result.output,
                    "error": "Tests failed after plan, rolled back",
                    "applied": 0,
                }
        return {
            "success": True,
            "tests_passed": True,
            "rolled_back": False,
            "applied": len(changes),
            "checkpoint": checkpoint,
        }

    def commit_changes(self, message: str, changes: list[FileChange]) -> None:
        if self._git.is_repo():
            self._git.commit(message, changes)

    def run_tests(self) -> dict:
        r = self._runner.run_tests()
        return {
            "success": r.success,
            "output": r.output,
            "command": r.command,
            "exit_code": r.exit_code,
        }

    def git_checkpoint(self, message: str) -> dict:
        try:
            h = self._git.create_checkpoint(message)
            return {"success": True, "commit_hash": h}
        except GitError as e:
            return {"success": False, "error": str(e)}

    def git_rollback(self) -> dict:
        try:
            self._git.rollback()
            return {"success": True}
        except GitError as e:
            return {"success": False, "error": str(e)}

    def is_git_clean(self) -> bool:
        return self._git.is_clean()
