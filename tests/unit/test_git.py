"""Application never stages or commits the user's work."""

from pathlib import Path
from unittest.mock import Mock

from git import Repo

from reducio.models import FileChange, RefactorPlan
from reducio.services import App


def test_recovery_preserves_dirty_git_state(temp_git_repo, monkeypatch):
    repo = Repo(temp_git_repo)
    main = temp_git_repo / "main.py"
    main.write_text("x = 2\n")
    repo.index.add(["main.py"])
    main.write_text("x = 3\n")
    (temp_git_repo / "untracked.bin").write_bytes(b"\xff\x00")
    head = repo.head.commit.hexsha
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
    assert repo.head.commit.hexsha == head
    assert (temp_git_repo / ".git/index").read_bytes() == index
    assert (temp_git_repo / "untracked.bin").read_bytes() == b"\xff\x00"


def test_read_only_discovery_clean_and_subdirectory(temp_git_repo):
    from reducio.git_safety import GitSafety

    git = GitSafety(str(temp_git_repo))
    index_before = (temp_git_repo / ".git/index").read_bytes()
    assert git.is_repo() and git.is_clean()
    nested = temp_git_repo / "nested"
    nested.mkdir()
    (nested / "untracked").write_text("keep")
    assert GitSafety(str(nested)).is_repo()
    assert not GitSafety(str(nested)).is_clean()
    assert (temp_git_repo / ".git/index").read_bytes() == index_before


def test_unborn_repository_uses_file_recovery(tmp_path, monkeypatch):
    repo = Repo.init(tmp_path)
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
    assert not repo.head.is_valid() and not (tmp_path / ".git/index").exists()
    assert source.read_text() == "x = 1\n"


def test_worktree_subdirectory_apply_does_not_touch_index(temp_git_repo, tmp_path, monkeypatch):
    repo = Repo(temp_git_repo)
    worktree = tmp_path / "linked"
    repo.git.worktree("add", "--detach", str(worktree), "HEAD")
    linked = Repo(worktree)
    index = Path(linked.git_dir) / "index"
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
    assert linked.head.commit.hexsha == repo.head.commit.hexsha
