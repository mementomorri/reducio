"""Git safety on non-repositories."""

import pytest

from reducio.git_safety import GitError, GitSafety


def test_checkpoint_requires_repo(tmp_path):
    git = GitSafety(str(tmp_path))
    assert not git.is_repo()
    with pytest.raises(GitError):
        git.create_checkpoint("x")
