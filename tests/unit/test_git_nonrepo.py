"""Git discovery is read-only, including non-repository targets."""

from reducio.git_safety import GitSafety


def test_nonrepo_is_clean(tmp_path):
    git = GitSafety(str(tmp_path))
    assert not git.is_repo()
    assert git.is_clean()
    for retired in ("create_checkpoint", "rollback", "commit"):
        assert not hasattr(git, retired)
