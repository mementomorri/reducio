"""Git discovery is read-only, including non-repository targets."""

from reducio.compare import worktree_clean


def test_nonrepo_is_clean(tmp_path):
    assert worktree_clean(str(tmp_path))
