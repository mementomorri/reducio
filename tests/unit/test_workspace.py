"""Exact-content application and pre-write rejection contracts."""

import pytest

from reducio.models import FileChange
from reducio.runner import TestResult as RunnerTestResult
from reducio.workspace import PathEscapeError, Workspace


def change(path="a.py", before="x = 1\n", after="x = 2\n", operation="replace"):
    return FileChange(
        path=path, original=before, modified=after, operation=operation, description="change"
    )


def test_path_escape(tmp_path):
    with pytest.raises(PathEscapeError):
        Workspace(str(tmp_path)).read_file("../../etc/passwd")


def test_apply_changes_no_git(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    assert Workspace(str(tmp_path)).apply_changes_safe([change()])["success"]
    assert f.read_bytes() == b"x = 2\n"


@pytest.mark.parametrize(
    "changes",
    [
        [change(), change()],
        [change(before="stale")],
        [change(after="def broken(:")],
        [change(before="", operation="create")],
        [change(path="missing.py")],
    ],
)
def test_invalid_batch_never_writes(tmp_path, changes):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    result = Workspace(str(tmp_path)).apply_changes_safe(changes)
    assert not result["success"] and result["recovery_status"] == "not_needed"
    assert f.read_bytes() == b"x = 1\n"


def test_empty_file_replacement_and_creation_are_distinct(tmp_path):
    f = tmp_path / "a.py"
    f.touch()
    assert Workspace(str(tmp_path)).apply_changes_safe([change(before="")])["success"]
    assert f.read_text() == "x = 2\n"


def test_test_failure_reports_zero_applied(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n")
    ws = Workspace(str(tmp_path))
    monkeypatch.setattr(
        ws._runner, "run_tests", lambda: RunnerTestResult(False, "fail", "pytest", 1)
    )
    result = ws.apply_changes_safe([change()], run_tests=True)
    assert not result["success"] and result["rolled_back"] and result["applied"] == 0
    assert (tmp_path / "a.py").read_text() == "x = 1\n"
