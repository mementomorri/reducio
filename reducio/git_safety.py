"""Git checkpoint and rollback for safe refactoring."""

from __future__ import annotations

from pathlib import Path

from git import InvalidGitRepositoryError, Repo

from reducio.models import FileChange


class GitError(Exception):
    pass


class GitSafety:
    def __init__(self, path: str):
        self.path = Path(path).resolve()
        self._repo: Repo | None = None

    def is_repo(self) -> bool:
        return (self.path / ".git").exists()

    def _open(self) -> Repo:
        if not self.is_repo():
            raise GitError(f"not a git repository: {self.path}")
        if self._repo is None:
            try:
                self._repo = Repo(self.path)
            except InvalidGitRepositoryError as e:
                raise GitError(str(e)) from e
        return self._repo

    def is_clean(self) -> bool:
        if not self.is_repo():
            return True
        return not self._open().is_dirty(untracked_files=True)

    def create_checkpoint(self, message: str) -> str:
        repo = self._open()
        repo.git.add(A=True)
        commit = repo.index.commit(message)
        return commit.hexsha[:8]

    def rollback(self) -> None:
        repo = self._open()
        head = repo.head.commit
        if not head.parents:
            raise GitError("no parent commit to rollback to")
        repo.head.reset(head.parents[0], index=True, working_tree=True)

    def commit(self, message: str, changes: list[FileChange]) -> None:
        repo = self._open()
        for change in changes:
            repo.index.add([change.path])
        repo.index.commit(message)
