"""Application never stages or commits the user's work."""

import subprocess
from pathlib import Path
from unittest.mock import Mock

from reducio.models import FileChange, RefactorPlan
from reducio.services import App


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def test_recovery_preserves_dirty_git_state(temp_git_repo, monkeypatch):
    main = temp_git_repo / "main.py"
    main.write_text("x = 2\n")
    git(temp_git_repo, "add", "main.py")
    main.write_text("x = 3\n")
    (temp_git_repo / "untracked.bin").write_bytes(b"\xff\x00")
    head = git(temp_git_repo, "rev-parse", "HEAD")
    index = (temp_git_repo / ".git/index").read_bytes()
    app = App(str(temp_git_repo))

    def fail():
        raise OSError("runner unavailable")

    monkeypatch.setattr(app.workspace._runner, "run_tests", fail)
    result = app.apply_plan(
        RefactorPlan(
            session_id="dirty",
            description="update",
            changes=[
                FileChange(
                    path="main.py", original="x = 3\n", modified="x = 99\n", description="update"
                )
            ],
        ),
        run_tests=True,
    )
    assert not result.success
    assert result.recovery_status == "restored"
    assert main.read_text() == "x = 3\n"
    assert git(temp_git_repo, "rev-parse", "HEAD") == head
    assert (temp_git_repo / ".git/index").read_bytes() == index
    assert (temp_git_repo / "untracked.bin").read_bytes() == b"\xff\x00"


def test_read_only_discovery_clean_and_subdirectory(temp_git_repo):
    from reducio.compare import worktree_clean

    index_before = (temp_git_repo / ".git/index").read_bytes()
    assert worktree_clean(str(temp_git_repo))
    nested = temp_git_repo / "nested"
    nested.mkdir()
    (nested / "untracked").write_text("keep")
    assert not worktree_clean(str(nested))
    assert (temp_git_repo / ".git/index").read_bytes() == index_before


def test_unborn_repository_uses_file_recovery(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "a.py"
    source.write_text("x = 1\n")
    app = App(str(tmp_path))
    monkeypatch.setattr(app.workspace._runner, "run_tests", Mock(side_effect=OSError("launch")))
    result = app.apply_plan(
        RefactorPlan(
            session_id="unborn",
            description="change",
            changes=[
                FileChange(
                    path="a.py", original="x = 1\n", modified="x = 2\n", description="change"
                )
            ],
        ),
        run_tests=True,
    )
    assert result.recovery_status == "restored"
    assert not (tmp_path / ".git/index").exists()
    assert source.read_text() == "x = 1\n"


def test_worktree_subdirectory_apply_does_not_touch_index(temp_git_repo, tmp_path, monkeypatch):
    worktree = tmp_path / "linked"
    git(temp_git_repo, "worktree", "add", "--detach", str(worktree), "HEAD")
    index = Path(git(worktree, "rev-parse", "--absolute-git-dir")) / "index"
    before = index.read_bytes()
    nested = worktree / "src"
    nested.mkdir()
    source = nested / "a.py"
    source.write_text("x = 1\n")
    app = App(str(nested))
    monkeypatch.setattr(app.workspace._runner, "run_tests", Mock(side_effect=OSError("launch")))
    result = app.apply_plan(
        RefactorPlan(
            session_id="linked",
            description="change",
            changes=[
                FileChange(
                    path="a.py", original="x = 1\n", modified="x = 2\n", description="change"
                )
            ],
        ),
        run_tests=True,
    )
    assert result.recovery_status == "restored"
    assert source.read_text() == "x = 1\n" and index.read_bytes() == before
    assert git(worktree, "rev-parse", "HEAD") == git(temp_git_repo, "rev-parse", "HEAD")
