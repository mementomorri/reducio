"""Workspace safety tests."""

import pytest

from reducio.runner import TestResult as RunnerTestResult
from reducio.workspace import PathEscapeError, Workspace


def test_path_escape(tmp_path):
    ws = Workspace(str(tmp_path))
    with pytest.raises(PathEscapeError):
        ws.read_file("../../etc/passwd")


def test_apply_changes_no_git(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ws = Workspace(str(tmp_path))
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    r = ws.apply_changes_safe([("a.py", diff)], run_tests=False)
    assert r["success"]
    assert f.read_text() == "x = 2\n"


def test_apply_changes_rollback_on_bad_diff(temp_git_repo):
    ws = Workspace(str(temp_git_repo))
    main = temp_git_repo / "main.py"
    good = "--- a/main.py\n+++ b/main.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    bad = "@@@ not a valid hunk @@@"
    r = ws.apply_changes_safe([("main.py", good), ("main.py", bad)], run_tests=False)
    assert not r["success"]
    assert r["recovery_status"] == "not_needed"
    assert main.read_text().strip() == "x = 1"


def test_apply_diff_refuses_create_over_existing(tmp_path):
    # A create diff (empty original) targeting an existing file must fail loudly and
    # leave the file untouched — never prepend the new content in front of the old.
    f = tmp_path / "exists.py"
    f.write_text("KEEP = 1\n")
    ws = Workspace(str(tmp_path))
    create_diff = "--- /dev/null\n+++ b/exists.py\n@@ -0,0 +1,1 @@\n+NEW = 2\n"
    r = ws.apply_changes_safe([("exists.py", create_diff)], run_tests=False)
    assert not r["success"]
    assert "refusing to create" in r["error"]
    assert f.read_text() == "KEEP = 1\n"  # not prepended, not merged


def test_apply_changes_no_git_restores_on_failure(tmp_path):
    # Non-git target: a mid-batch failure must restore earlier-applied changes too.
    a = tmp_path / "a.py"
    a.write_text("a = 1\n")
    ws = Workspace(str(tmp_path))
    good = "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-a = 1\n+a = 2\n"
    bad = "@@@ not a valid hunk @@@"
    r = ws.apply_changes_safe([("a.py", good), ("a.py", bad)], run_tests=False)
    assert not r["success"]
    assert r["recovery_status"] == "not_needed"
    assert r["applied"] == 0
    assert a.read_text() == "a = 1\n"  # restored even without git


def test_apply_changes_rolls_back_invalid_python(temp_git_repo):
    # A diff that applies cleanly but yields un-parseable Python must roll back
    # even when the target repo has no tests to trip on (ROADMAP P2).
    ws = Workspace(str(temp_git_repo))
    main = temp_git_repo / "main.py"
    bad = "--- a/main.py\n+++ b/main.py\n@@ -1,1 +1,1 @@\n-x = 1\n+def broken(:\n"
    r = ws.apply_changes_safe([("main.py", bad)], run_tests=False)
    assert not r["success"]
    assert r.get("rolled_back")
    assert "invalid Python" in r["error"]
    assert main.read_text().strip() == "x = 1"


def test_apply_changes_test_failure_reports_zero_applied(temp_git_repo, monkeypatch):
    ws = Workspace(str(temp_git_repo))
    diff = "--- a/main.py\n+++ b/main.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    monkeypatch.setattr(
        ws._runner,
        "run_tests",
        lambda: RunnerTestResult(success=False, output="fail", command="pytest", exit_code=1),
    )
    r = ws.apply_changes_safe([("main.py", diff)], run_tests=True)
    assert not r["success"]
    assert r.get("rolled_back")
    assert r["applied"] == 0
    assert (temp_git_repo / "main.py").read_text().strip() == "x = 1"
