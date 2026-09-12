"""Read-only Git discovery and dirty-tree inspection."""

from __future__ import annotations

from pathlib import Path

from git import InvalidGitRepositoryError, Repo


class GitError(Exception):
    pass


class GitSafety:
    def __init__(self, path: str):
        self.path = Path(path).resolve()
        self._repo: Repo | None = None

    def is_repo(self) -> bool:
        try:
            self._repo = Repo(self.path, search_parent_directories=True)
            return True
        except InvalidGitRepositoryError:
            return False

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
        repo = self._open()
        # Even status/diff may refresh Git's index unless optional locks are disabled.
        with repo.git.custom_environment(GIT_OPTIONAL_LOCKS="0"):
            return not repo.is_dirty(untracked_files=True)
