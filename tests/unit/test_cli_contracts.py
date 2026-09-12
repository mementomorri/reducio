"""Observable plan/apply, configuration, and input-validation contracts."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from typer.testing import CliRunner

from reducio.cli import app
from reducio.models import FileChange, RefactorPlan, RefactorResult
from reducio.session import SessionStore

COMMANDS = ["deduplicate", "idiomatize", "pattern", "apply"]


@pytest.mark.parametrize("command", COMMANDS)
def test_opt_in_runner_flag(cli_case, command):
    result = cli_case.invoke(command, "--yes", "--run-tests", "--quiet")
    assert result.exit_code == 0, result.output
    cli_case.service.apply_plan.assert_called_once_with(cli_case.plan, run_tests=True)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("success", [False, True])
def test_apply_report_includes_failures(cli_case, command, success, tmp_path):
    cli_case.service.apply_plan.return_value = RefactorResult(
        session_id=cli_case.plan.session_id,
        success=success,
        changes=[],
        tests_passed=False,
        error=None if success else "requested tests failed",
        test_status="not_run" if success else "failed",
    )
    (tmp_path / "sample.py").write_text("x = 1\n")
    result = cli_case.invoke(command, "--yes", "--report", "--output-dir", "reports", "--quiet")
    assert result.exit_code == (0 if success else 1), result.output
    assert (tmp_path / "reports/reducio-report-test-session.md").exists()
    assert (tmp_path / "reports/reducio-report-test-session.json").exists()


@pytest.mark.parametrize("success", [False, True])
def test_report_failure_distinguishes_applied_state(cli_case, monkeypatch, success):
    cli_case.service.apply_plan.return_value.success = success
    monkeypatch.setattr("reducio.cli.Reporter.generate", Mock(side_effect=OSError("read-only")))
    result = cli_case.invoke("idiomatize", "--yes", "--report", "--quiet")
    assert result.exit_code == 1
    assert ("Changes applied" if success else "Application failed") in result.output
    assert "report failed" in result.output


@pytest.fixture
def cli_case(tmp_path, monkeypatch):
    monkeypatch.setattr("reducio.cli._is_interactive", lambda: True)
    monkeypatch.chdir(tmp_path)
    for key in ("REDUCIO_MODEL", "REDUCIO_VERBOSE", "REDUCIO_PREFER_LOCAL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    plan = RefactorPlan(
        session_id="test-session",
        description="Proposed changes",
        changes=[
            FileChange(
                path="sample.py", original="x = 1\n", modified="x = 2\n", description="Change x"
            )
        ],
    )
    service = SimpleNamespace(
        deduplicate=AsyncMock(return_value=plan),
        idiomatize=AsyncMock(return_value=plan),
        pattern=AsyncMock(return_value=plan),
        apply_plan=Mock(
            return_value=RefactorResult(
                session_id=plan.session_id, success=True, changes=plan.changes, tests_passed=True
            )
        ),
    )
    factory = Mock(return_value=service)
    monkeypatch.setattr("reducio.cli._new_app", factory)
    SessionStore().save_plan(plan)

    def invoke(command, *options, input=None):
        args = [command]
        if command == "apply":
            args.append(plan.session_id)
        return CliRunner().invoke(app, [*args, *options], input=input)

    return SimpleNamespace(plan=plan, service=service, factory=factory, invoke=invoke)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("success", [False, True])
def test_apply_outcomes(cli_case, command, success):
    cli_case.service.apply_plan.return_value = RefactorResult(
        session_id=cli_case.plan.session_id,
        success=success,
        changes=cli_case.plan.changes,
        tests_passed=success,
        error=None if success else "validation rejected the change",
    )
    result = cli_case.invoke(command, "--yes", "--quiet")
    assert result.exit_code == (0 if success else 1), result.output
    assert "Session ID: test-session" in result.output
    assert ("Applied." in result.output) is success
    if not success:
        assert "Failed: validation rejected" in result.output
    cli_case.service.apply_plan.assert_called_once_with(cli_case.plan, run_tests=False)


@pytest.mark.parametrize("command", COMMANDS)
def test_empty_plan_never_applies_or_prompts(cli_case, command):
    cli_case.plan.changes.clear()
    SessionStore().save_plan(cli_case.plan)
    result = cli_case.invoke(command)
    assert result.exit_code == 0, result.output
    assert "No changes to apply." in result.output
    assert "Applied." not in result.output
    cli_case.service.apply_plan.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
def test_declined_approval_never_applies(cli_case, command):
    result = cli_case.invoke(command, input="n\n")
    assert result.exit_code == 0
    assert "Session ID: test-session" in result.output
    cli_case.service.apply_plan.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS[:-1])
@pytest.mark.parametrize("empty", [False, True])
def test_dry_run_reports_and_session_ids(cli_case, command, empty):
    if empty:
        cli_case.plan.changes.clear()
    result = cli_case.invoke(command, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "Session ID: test-session" in result.output
    report_line = next(
        line for line in result.output.splitlines() if line.startswith("Dry run report: ")
    )
    assert Path(report_line.removeprefix("Dry run report: ")).is_file()
    cli_case.service.apply_plan.assert_not_called()


@pytest.mark.parametrize(
    "options,answer,code,applied",
    [
        ([], "n\n", 1, False),
        ([], "y\nn\n", 0, False),
        ([], "y\ny\n", 0, True),
        (["--yes"], None, 0, True),
    ],
)
def test_saved_plan_dirty_warning(cli_case, monkeypatch, options, answer, code, applied):
    monkeypatch.setattr("reducio.cli.GitSafety.is_repo", lambda self: True)
    monkeypatch.setattr("reducio.cli.GitSafety.is_clean", lambda self: False)
    result = cli_case.invoke("apply", *options, input=answer)
    assert result.exit_code == code, result.output
    assert "Warning: uncommitted changes" in result.output
    assert ("Continue anyway?" in result.output) is ("--yes" not in options)
    assert bool(cli_case.service.apply_plan.call_count) is applied


@pytest.mark.parametrize(
    "command", [["sessions", "list"], ["sessions", "show", "session"], ["sessions", "cleanup"]]
)
@pytest.mark.parametrize("target_kind", ["missing", "file"])
def test_session_targets_validated_before_storage(tmp_path, command, target_kind):
    target = tmp_path / "target"
    if target_kind == "file":
        target.write_text("not a directory")
    result = CliRunner().invoke(app, [*command, "--path", str(target)])
    assert result.exit_code == 2
    assert "Not a directory" in result.output
    assert not (target / ".reducio").exists()
    if target_kind == "missing":
        assert not target.exists()


def test_negative_cleanup_age_does_not_create_storage(tmp_path):
    result = CliRunner().invoke(
        app, ["sessions", "cleanup", "--path", str(tmp_path), "--days", "-1"]
    )
    assert result.exit_code == 2
    assert not (tmp_path / ".reducio").exists()


@pytest.mark.parametrize(
    "command",
    ["analyze", "compare", "deduplicate", "idiomatize", "pattern", "check", "apply", "report"],
)
def test_invalid_explicit_config_is_clean_error(tmp_path, monkeypatch, command):
    monkeypatch.chdir(tmp_path)
    args = [command]
    if command == "compare":
        args += ["--base", "HEAD"]
    if command == "apply":
        args += ["some-session"]
    result = CliRunner().invoke(app, [*args, "--config", "missing.yaml"])
    assert result.exit_code == 2
    assert "Configuration file not found" in result.output
    assert "Traceback" not in result.output
    assert not (tmp_path / ".reducio").exists()


@pytest.mark.parametrize(
    "options,environment,expected",
    [
        ([], {}, ("file-model", "anthropic", True)),
        (
            [],
            {"REDUCIO_MODEL": "env-model", "REDUCIO_LLM_API": "openai", "REDUCIO_VERBOSE": "false"},
            ("env-model", "openai", False),
        ),
        (
            ["--model", "cli-model", "--llm-api", "anthropic", "-v"],
            {"REDUCIO_MODEL": "env-model", "REDUCIO_LLM_API": "openai", "REDUCIO_VERBOSE": "false"},
            ("cli-model", "anthropic", True),
        ),
        (["--model", "", "--no-verbose"], {"REDUCIO_MODEL": "env-model"}, ("", "anthropic", False)),
    ],
)
def test_cli_configuration_precedence(cli_case, monkeypatch, options, environment, expected):
    Path(".reducio.yaml").write_text("model: file-model\nllm_api: anthropic\nverbose: true\n")
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    result = cli_case.invoke("idiomatize", "--dry-run", *options)
    assert result.exit_code == 0, result.output
    cfg = cli_case.factory.call_args.args[1]
    assert (cfg.model, cfg.llm_api, cfg.verbose) == expected


def test_retired_preferences_do_not_initialize(cli_case):
    result = cli_case.invoke("analyze", "--prefer-local", "--prefer-remote")
    assert result.exit_code == 2
    cli_case.factory.assert_not_called()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("yes,empty", [(False, False), (True, False), (False, True)])
def test_unattended_application_requires_yes(cli_case, monkeypatch, command, yes, empty):
    monkeypatch.setattr("reducio.cli._is_interactive", lambda: False)
    if empty:
        cli_case.plan.changes.clear()
        SessionStore().save_plan(cli_case.plan)
    result = cli_case.invoke(command, "--quiet", *(["--yes"] if yes else []))
    assert result.exit_code == (0 if yes or empty else 1), result.output
    if not yes and not empty:
        assert "--yes" in result.output and "--dry-run" in result.output
        cli_case.service.apply_plan.assert_not_called()
