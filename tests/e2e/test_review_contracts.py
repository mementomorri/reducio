"""Real CLI invocations from outside the target, including persisted replay."""

import json
import subprocess
import sys

import pytest


def run(*args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "reducto.cli", *map(str, args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("command", ["analyze", "check", "idiomatize", "pattern"])
@pytest.mark.parametrize("override", [False, True])
def test_report_generation_and_retrieval_outside_target(tmp_path, command, override):
    target = tmp_path / "target"
    target.mkdir()
    source = "def f(x):\n    return x == None\n"
    (target / "a.py").write_text(source)
    args = [command, target]
    if command == "pattern":
        args = [command, "singleton", target]
    args += ["--dry-run"] if command in {"idiomatize", "pattern"} else ["--report"]
    options = ["--output-dir", "custom"] if override else []
    result = run(*args, *options, "--quiet", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    reports = tmp_path / "custom" if override else target / ".reducto"
    assert list(reports.glob("*.md"))
    assert not (tmp_path / ".reducto").exists()
    retrieved = run("report", "-C", target, *options, cwd=tmp_path)
    assert retrieved.returncode == 0, retrieved.stderr
    if command == "idiomatize":
        assert "-    return x == None" in retrieved.stdout
        assert "+    return x is None" in retrieved.stdout
        envelope = json.loads(next((target / ".reducto/sessions").glob("*.json")).read_text())
        session_id = envelope["plan"]["session_id"]
        shown = run("sessions", "show", session_id, "-C", target, cwd=tmp_path)
        assert "+++ b/a.py" in shown.stdout
        assert "heuristic" in shown.stdout
    assert (target / "a.py").read_text() == source


@pytest.mark.parametrize("command", ["apply", "report", "sessions"])
def test_invalid_session_ids_are_clean_errors(tmp_path, command):
    args = [command, "show", "../escape"] if command == "sessions" else [command, "../escape"]
    result = run(*args, cwd=tmp_path)
    assert result.returncode == 2
    assert "session ID" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / ".reducto").exists()


def test_real_saved_apply_shows_diff_with_yes_and_preserves_behavior(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    source = "def f():\n    out = []\n    for x in range(3):\n        out.append(x * 2)\n    return out\n"
    path = target / "a.py"
    path.write_text(source)
    result = run("idiomatize", target, "--dry-run", "--quiet", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    session = json.loads(next((target / ".reducto/sessions").glob("*.json")).read_text())["plan"]
    result = run("apply", session["session_id"], target, "--yes", "--quiet", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "+++ b/a.py" in result.stdout and result.stdout.index(
        "+++ b/a.py"
    ) < result.stdout.index("Applied.")
    assert path.read_text() != source
    before, after = {}, {}
    exec(source, before)
    exec(path.read_text(), after)
    assert before["f"]() == after["f"]() == [0, 2, 4]


def test_incomplete_session_cannot_replay(tmp_path):
    from reducto.models import FileChange, RefactorPlan
    from reducto.session import SessionStore

    plan = RefactorPlan(
        session_id="failed",
        complete=False,
        description="partial proposal",
        changes=[FileChange(path="a.py", original="", modified="x=1\n", description="create")],
    )
    SessionStore(str(tmp_path / ".reducto/sessions")).save_plan(plan)
    result = run("apply", "failed", "--yes", "--quiet", cwd=tmp_path)
    assert result.returncode == 1 and "incomplete" in result.stderr
    assert not (tmp_path / "a.py").exists()
