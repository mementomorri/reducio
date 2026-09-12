"""Behavioral and fault-injection coverage for scoped application."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from reducio import recovery
from reducio.analysis import analyze_files
from reducio.idioms import rewrite
from reducio.models import AppConfig, FileChange, FileInfo, RefactorPlan, RefactorResult
from reducio.reporter import Reporter
from reducio.runner import ProjectRunner
from reducio.runner import TestResult as RunnerResult
from reducio.services import App, _change_to_diff
from reducio.workspace import Workspace


def plan_for(tmp_path, before="def f():\n    return 1\n", after="def f():\n    return 2\n"):
    (tmp_path / "a.py").write_bytes(before.encode())
    return RefactorPlan(
        session_id="safety",
        description="update",
        changes=[FileChange(path="a.py", original=before, modified=after, description="update")],
    )


@pytest.mark.parametrize(
    "body",
    [
        "out = [99]\nfor x in range(2):\n    out.append(x)\nreturn out",
        "out = []\nalias = out\nfor x in range(2):\n    out.append(x)\nreturn alias",
        "out = []\nfor x in range(2):\n    out.append(x)\nreturn x",
        "out = []\nfor x in range(2):\n    out.append(x)\n    print(x)\nreturn out",
        "out = []\nfor x in range(2):\n    out.append(x)\nelse:\n    out.append(9)\nreturn out",
        "out = {}\nfor x in range(2):\n    out[x] = len(out)\nreturn out",
        "out = []\nfor x in range(2):\n    out.append(side_effect(x))\nreturn out",
        "out = []\nfor x in []:\n    out.append(x)\nreturn out",
        "out = []\nfor x in range(2000):\n    out.append(x)\nreturn out",
        "out = []\nfor x in range(2):\n    out.append(x) # preserve\nreturn out",
        "try:\n    out = []\n    for x in range(2):\n        out.append(x)\nexcept Exception:\n    return out\nreturn out",
        "out = []\nfor x in range(2):\n    out.append(x)\nreturn lambda: x",
        "out = []\nfor x in range(2):\n    out.append(x)\nreturn locals()",
        "global out\nout = []\nfor x in range(2):\n    out.append(x)\nreturn out",
        "x = 1\nwhile len(x) == 0:\n    x = custom()\nreturn x",
        "return x == None",
        "if len(x) > 0:\n    return 1\nreturn 0",
        "if x == 1 or x == side_effect():\n    return 1\nreturn 0",
    ],
)
def test_uncertain_rewrites_are_skipped(body):
    source = (
        "def f(unknown=None):\n" + "\n".join("    " + line for line in body.splitlines()) + "\n"
    )
    assert rewrite(source, "a.py")[0] == source


@pytest.mark.parametrize(
    "body",
    [
        "out = []\nfor x in range(3):\n    out.append(x * 2)\nreturn out",
        "out = {}\nfor x in [1, 2, 3]:\n    out[x] = x * 2\nreturn out",
        "out = []\nfor x in [-1, 0, 1]:\n    if x > 0:\n        out.append(x + 1)\nreturn out",
        "x = None\nreturn x == None",
        "x = 1\nreturn x != None",
        "xs = [1]\nif len(xs) > 0:\n    return 1\nreturn 0",
        "xs = []\nif len(xs) == 0:\n    return 1\nreturn 0",
        "x = 'a'\nif x == 'a' or x == 'b':\n    return 1\nreturn 0",
    ],
)
def test_supported_rewrites_preserve_results_and_surrounding_bytes(body):
    prefix = '# π: "x == None"\r\nTEXT = "len(x) > 0"\r\n\r\n'
    suffix = "\r\n# final comment\r\n"
    source = (
        prefix
        + "def f():\r\n"
        + "\r\n".join("    " + line for line in body.splitlines())
        + "\r\n"
        + suffix
    )
    updated, descriptions, _ = rewrite(source, "a.py")
    assert descriptions and updated != source
    assert updated.startswith(prefix) and updated.endswith(suffix)
    before, after = {}, {}
    exec(source, before)
    exec(updated, after)
    assert before["f"]() == after["f"]()


@pytest.mark.parametrize(
    "binding", ["def range(n):\n    return []", "range = custom", "from x import range"]
)
def test_shadowed_range_is_not_assumed_builtin(binding):
    source = (
        binding
        + "\ndef f():\n    out = []\n    for x in range(3):\n        out.append(x)\n    return out\n"
    )
    assert rewrite(source, "a.py")[0] == source


@pytest.mark.parametrize("parameter", ["x", "out"])
def test_rebinding_parameter_does_not_change_finalizer_timing(parameter):
    source = (
        "events = []\n"
        "class Watched:\n"
        "    def __del__(self):\n"
        "        events.append('released')\n"
        f"def f({parameter}):\n"
        "    out = []\n"
        "    for x in range(3):\n"
        "        out.append(x)\n"
        "    return len(events)\n"
    )
    updated, descriptions, diagnostics = rewrite(source, "a.py")
    assert updated == source and not descriptions and diagnostics
    before, after = {}, {}
    exec(source, before)
    exec(updated, after)
    assert before["f"](before["Watched"]()) == after["f"](after["Watched"]())


def test_previously_bound_loop_variable_is_not_rewritten():
    source = (
        "def f():\n"
        "    x = object()\n"
        "    out = []\n"
        "    for x in range(3):\n"
        "        out.append(x)\n"
        "    return out\n"
    )
    assert rewrite(source, "a.py")[0] == source


def test_default_apply_never_runs_tests_and_measures_full_files(tmp_path, monkeypatch):
    plan = plan_for(
        tmp_path,
        "def f(x):\n    if x:\n        return 1\n    return 2\n",
        "def f(x):\n    return 1\n",
    )
    app = App(str(tmp_path))
    runner = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(app.workspace._runner, "run_tests", runner)
    result = app.apply_plan(plan)
    assert result.success and not result.tests_passed
    assert result.test_status == "not_run"
    runner.assert_not_called()
    assert result.metrics_before.cyclomatic_complexity == 2
    assert result.metrics_after.cyclomatic_complexity == 1
    expected = analyze_files(
        [FileInfo(path="a.py", content=(tmp_path / "a.py").read_text())],
        AppConfig(),
        "affected files",
    )
    assert result.measurements_after == expected
    report = Reporter(target=tmp_path).generate(result)
    assert "improved" in report.read_text()
    assert json.loads(report.with_suffix(".json").read_text())["test_status"] == "not_run"
    assert "maintainability_index" not in result.model_dump()["metrics_before"]


@pytest.mark.parametrize("failure", ["returned", "exception", "timeout", "metrics"])
def test_post_write_failure_restores_bytes_modes_and_new_files(tmp_path, monkeypatch, failure):
    plan = plan_for(tmp_path, "x = 1\r\n", "x = 2\r\n")
    plan.changes.append(
        FileChange(path="new/nested.py", original="", modified="x = 3\n", description="create")
    )
    source = tmp_path / "a.py"
    source.chmod(0o751)
    app = App(str(tmp_path))
    if failure == "metrics":
        import reducio.analysis

        original = reducio.analysis.analyze_files
        calls = 0

        def measure(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("measurement failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(reducio.analysis, "analyze_files", measure)
    else:
        runner = Mock(return_value=RunnerResult(False, "failed", "explicit", 1))
        if failure == "exception":
            runner.side_effect = OSError("launch")
        if failure == "timeout":
            runner.side_effect = subprocess.TimeoutExpired("explicit", 1)
        monkeypatch.setattr(app.workspace._runner, "run_tests", runner)
    result = app.apply_plan(plan, run_tests=failure != "metrics")
    assert not result.success
    assert result.recovery_status == "restored"
    assert source.read_bytes() == b"x = 1\r\n"
    assert stat.S_IMODE(source.stat().st_mode) == 0o751
    assert not (tmp_path / "new").exists()
    assert Path(result.backup_location).is_dir()
    assert result.measurements_before == result.measurements_after
    if failure != "metrics":
        assert result.measurements_attempted.file_lines["new/nested.py"] == 1


@pytest.mark.parametrize("kind", ["concurrent", "corrupt_backup", "restore_error"])
def test_recovery_failure_retains_evidence(tmp_path, monkeypatch, kind):
    plan = plan_for(tmp_path)
    app = App(str(tmp_path))
    real_replace = recovery.replace_bytes

    def fail_tests():
        if kind == "concurrent":
            (tmp_path / "a.py").write_text("user = 'concurrent'\n")
        elif kind == "corrupt_backup":
            next((tmp_path / ".reducio/recovery").glob("*/0.bin")).write_bytes(b"corrupt")
        else:

            def fail_replace(path, *args):
                if path.name == "a.py":
                    raise PermissionError("restore denied")
                return real_replace(path, *args)

            monkeypatch.setattr(recovery, "replace_bytes", fail_replace)
        return RunnerResult(False, "failure", "explicit", 1)

    monkeypatch.setattr(app.workspace._runner, "run_tests", fail_tests)
    result = app.apply_plan(plan, run_tests=True)
    assert not result.success and result.recovery_status == "failed"
    assert result.recovery_errors and Path(result.backup_location).exists()
    assert (tmp_path / "a.py").read_text() != plan.changes[0].original
    assert result.measurements_after is not None
    report = Reporter(target=tmp_path).generate(result)
    assert "Recovery: failed" in report.read_text()


def test_mid_batch_write_failure_restores_previous_write(tmp_path, monkeypatch):
    plan = plan_for(tmp_path)
    plan.changes.append(FileChange(path="b.py", original="", modified="x = 2", description="new"))
    original = recovery.replace_bytes

    def fail(path, *args):
        if path.name == "b.py":
            raise PermissionError("second write")
        return original(path, *args)

    monkeypatch.setattr(recovery, "replace_bytes", fail)
    result = App(str(tmp_path)).apply_plan(plan)
    assert not result.success and result.recovery_status == "restored"
    assert (tmp_path / "a.py").read_text() == plan.changes[0].original
    assert not (tmp_path / "b.py").exists()


@pytest.mark.parametrize("relative", ["../escape.py", ".git/config", ".reducio/recovery/evil.py"])
def test_unsafe_paths_rejected_before_writes(tmp_path, relative):
    with pytest.raises(ValueError):
        recovery.safe_target(tmp_path, relative)


def test_symlink_and_hardlink_rejected(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("x=1")
    (tmp_path / "link.py").symlink_to(source)
    with pytest.raises(ValueError):
        recovery.safe_target(tmp_path, "link.py")
    os.link(source, tmp_path / "hard.py")
    with pytest.raises(ValueError):
        recovery.safe_target(tmp_path, "hard.py")


def test_retired_commit_configuration_is_rejected():
    with pytest.raises(ValueError, match="commit_changes"):
        AppConfig(commit_changes=False)


def test_test_status_overrules_legacy_boolean():
    result = RefactorResult(session_id="truth", success=True, changes=[], tests_passed=True)
    assert not result.tests_passed


@pytest.mark.parametrize(
    "cfg",
    [
        {"test_timeout_seconds": 0},
        {"test_command": []},
        {"test_command": [""]},
        {"test_runner": "automatic"},
    ],
)
def test_invalid_runner_config(cfg):
    with pytest.raises(ValueError):
        AppConfig(**cfg)


def test_missing_target_interpreter_is_error(tmp_path):
    result = ProjectRunner(str(tmp_path)).run_tests()
    assert result.status == "error" and not result.success


def test_explicit_argv_takes_precedence_and_is_shell_free(tmp_path, monkeypatch):
    cfg = AppConfig(
        test_command=[sys.executable, "-c", "print('ok; no shell')"],
        test_python="missing",
        test_runner="unittest",
    )
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "ok", ""))
    monkeypatch.setattr(subprocess, "run", run)
    result = ProjectRunner(str(tmp_path), cfg).run_tests()
    assert result.success and result.count is None
    assert run.call_args.args[0] == cfg.test_command
    assert run.call_args.kwargs["shell"] is False
    assert run.call_args.kwargs["cwd"] == tmp_path


@pytest.mark.parametrize("runner", ["pytest", "unittest"])
def test_builtin_zero_tests_fails(tmp_path, runner):
    result = ProjectRunner(
        str(tmp_path), AppConfig(test_python=sys.executable, test_runner=runner)
    ).run_tests()
    assert not result.success and result.status == "error" and result.count == 0


def test_unittest_executes_target_tests(tmp_path):
    (tmp_path / "test_target.py").write_text(
        "import unittest\nclass TestTarget(unittest.TestCase):\n    def test_yes(self):\n        self.assertEqual(1, 1)\n"
    )
    result = ProjectRunner(
        str(tmp_path), AppConfig(test_python=sys.executable, test_runner="unittest")
    ).run_tests()
    assert result.success and result.status == "passed" and result.count == 1


def test_runner_timeout(tmp_path):
    cfg = AppConfig(
        test_command=[sys.executable, "-c", "import time; time.sleep(10)"], test_timeout_seconds=1
    )
    result = ProjectRunner(str(tmp_path), cfg).run_tests()
    assert result.status == "error" and "timed out" in result.output


def test_target_venv_selected(tmp_path):
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    assert ProjectRunner(str(tmp_path)).command()[0] == str(python)


def test_public_single_diff_uses_recovery(tmp_path):
    plan = plan_for(tmp_path)
    result = Workspace(str(tmp_path)).apply_diff("a.py", _change_to_diff(plan.changes[0]))
    assert result["success"] and result["backup_location"]
