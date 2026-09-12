"""Opt-in inclusive severity gates and their public CLI contract."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from reducio.cli import _is_interactive, app
from reducio.quality_gate import LEVELS, evaluate_gate


@pytest.mark.parametrize("threshold", LEVELS)
@pytest.mark.parametrize("severity", LEVELS[1:])
def test_inclusive_gate(threshold, severity):
    result = evaluate_gate({severity: 1}, threshold)
    assert result["gate_failed"] == (
        threshold != "none" and LEVELS.index(severity) >= LEVELS.index(threshold)
    )
    assert not evaluate_gate({}, threshold)["gate_failed"]


def test_invalid_gate():
    with pytest.raises(ValueError):
        evaluate_gate({}, "invalid")


@pytest.mark.parametrize("threshold,code", [("none", 0), ("warning", 1), ("critical", 0)])
def test_cli_report_precedes_gate_exit(tmp_path, monkeypatch, threshold, code):
    monkeypatch.chdir(tmp_path)
    result = {"total_issues": 1, "critical": 0, "warning": 1, "info": 0, "issues": []}
    monkeypatch.setattr(
        "reducio.cli._new_app", lambda *a: SimpleNamespace(check=AsyncMock(return_value=result))
    )
    response = CliRunner().invoke(app, ["check", ".", "--fail-on", threshold, "--report"])
    assert response.exit_code == code, response.output
    reports = list((tmp_path / ".reducio").glob("reducio-check-*.md"))
    assert len(reports) == 1
    assert f"Quality gate: {threshold}" in reports[0].read_text()


def test_gate_precedence(tmp_path, monkeypatch):
    from reducio.cli import _get_cfg

    config = tmp_path / "config.yaml"
    config.write_text("check_fail_on: critical\n")
    assert _get_cfg(config).check_fail_on == "critical"
    monkeypatch.setenv("REDUCIO_CHECK_FAIL_ON", "warning")
    assert _get_cfg(config).check_fail_on == "warning"
    assert _get_cfg(config, check_fail_on="none").check_fail_on == "none"
    response = CliRunner().invoke(app, ["check", str(tmp_path), "--fail-on", "invalid"])
    assert response.exit_code == 2


@pytest.mark.parametrize(
    "ci,tty,expected", [("true", True, False), ("false", True, True), ("", False, False)]
)
def test_ci_approval_detection(monkeypatch, ci, tty, expected):
    monkeypatch.setenv("CI", ci)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: tty))
    assert _is_interactive() is expected
