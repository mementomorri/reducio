"""Real CLI invocations from outside the target, including persisted replay."""

import json
import subprocess
import sys

import pytest


def run(*args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "reducio.cli", *map(str, args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("command", ["analyze", "check", "deduplicate", "pattern"])
@pytest.mark.parametrize("override", [False, True])
def test_report_generation_and_retrieval_outside_target(tmp_path, command, override):
    target = tmp_path / "target"
    target.mkdir()
    source = "COUNT = 0\ndef f():\n    global COUNT\n    COUNT += 1\n    return COUNT\n"
    (target / "a.py").write_text(source)
    args = [command, target]
    if command == "pattern":
        args = [command, "singleton", target]
    args += ["--dry-run"] if command in {"deduplicate", "pattern"} else ["--report"]
    options = ["--output-dir", "custom"] if override else []
    result = run(*args, *options, "--quiet", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    reports = tmp_path / "custom" if override else target / ".reducio"
    assert list(reports.glob("*.md"))
    assert not (tmp_path / ".reducio").exists()
    retrieved = run("report", "-C", target, *options, cwd=tmp_path)
    assert retrieved.returncode == 0, retrieved.stderr
    if command == "pattern":
        assert "+++ b/singletons/" in retrieved.stdout
        envelope = json.loads(next((target / ".reducio/sessions").glob("*.json")).read_text())
        session_id = envelope["plan"]["session_id"]
        shown = run("sessions", "show", session_id, "-C", target, cwd=tmp_path)
        assert "+++ b/singletons/" in shown.stdout
        assert "template" in shown.stdout
    assert (target / "a.py").read_text() == source


@pytest.mark.parametrize("command", ["apply", "report", "sessions"])
def test_invalid_session_ids_are_clean_errors(tmp_path, command):
    args = [command, "show", "../escape"] if command == "sessions" else [command, "../escape"]
    result = run(*args, cwd=tmp_path)
    assert result.returncode == 2
    assert "session ID" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / ".reducio").exists()


def test_real_saved_apply_shows_diff_with_yes_and_creates_advisory_module(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    source = "COUNT = 0\ndef f():\n    global COUNT\n    COUNT += 1\n    return COUNT\n"
    path = target / "a.py"
    path.write_text(source)
    result = run("pattern", "singleton", target, "--dry-run", "--quiet", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    session = json.loads(next((target / ".reducio/sessions").glob("*.json")).read_text())["plan"]
    refused = run("apply", session["session_id"], target, "--quiet", cwd=tmp_path)
    assert refused.returncode == 1 and "--yes" in refused.stderr
    created = target / session["changes"][0]["path"]
    assert not created.exists()
    result = run("apply", session["session_id"], target, "--yes", "--quiet", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "+++ b/singletons/" in result.stdout and result.stdout.index(
        "+++ b/singletons/"
    ) < result.stdout.index("Applied.")
    assert path.read_text() == source and "class Singleton" in created.read_text()


def test_incomplete_session_cannot_replay(tmp_path):
    from reducio.models import FileChange, RefactorPlan
    from reducio.session import SessionStore

    plan = RefactorPlan(
        session_id="failed",
        complete=False,
        description="partial proposal",
        changes=[FileChange(path="a.py", original="", modified="x=1\n", description="create")],
    )
    SessionStore(str(tmp_path / ".reducio/sessions")).save_plan(plan)
    result = run("apply", "failed", "--yes", "--quiet", cwd=tmp_path)
    assert result.returncode == 1 and "incomplete" in result.stderr
    assert not (tmp_path / "a.py").exists()


@pytest.mark.parametrize("execute,exit_code", [(False, 0), (True, 0), (True, 1)])
def test_real_opt_in_after_only_tests_and_report(tmp_path, execute, exit_code):
    import yaml

    from reducio.models import FileChange, RefactorPlan
    from reducio.session import SessionStore

    target = tmp_path / "target"
    target.mkdir()
    (target / "a.py").write_text("x = 1\n")
    plan = RefactorPlan(
        session_id="optin",
        description="update",
        changes=[
            FileChange(path="a.py", original="x = 1\n", modified="x = 2\n", description="update")
        ],
    )
    SessionStore(str(target / ".reducio/sessions")).save_plan(plan)
    code = (
        "from pathlib import Path; import sys; "
        "assert Path('a.py').read_text() == 'x = 2\\n'; "
        "Path('test-marker').write_text('ran'); " + f"sys.exit({exit_code})"
    )
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(yaml.safe_dump({"test_command": [sys.executable, "-c", code]}))
    result = run(
        "apply",
        "optin",
        target,
        "--config",
        cfg,
        "--yes",
        "--report",
        "--output-dir",
        "reports",
        "--quiet",
        *(["--run-tests"] if execute else []),
        cwd=tmp_path,
    )
    failed = execute and exit_code != 0
    assert result.returncode == (1 if failed else 0), result.stderr
    assert (target / "test-marker").exists() is execute
    assert (target / "a.py").read_text() == ("x = 1\n" if failed else "x = 2\n")
    report = json.loads((tmp_path / "reports/reducio-report-optin.json").read_text())
    assert report["test_status"] == ("not_run" if not execute else "failed" if failed else "passed")
    assert report["recovery_status"] == ("restored" if failed else "not_needed")
