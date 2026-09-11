"""Every report format describes the same complete, versioned measurements."""

import builtins
import json
import re

import pytest
from typer.testing import CliRunner

from reducio.analysis import analyze_files
from reducio.cli import app
from reducio.models import AppConfig, CompareResult, FileInfo
from reducio.visual_report import (
    ReportError,
    ReportFormat,
    html_report,
    markdown_report,
    write_reports,
)


def overview(code="def f():\n    return 1\n", path="example.py"):
    return analyze_files([FileInfo(path=path, content=code)], AppConfig())


def test_all_formats_share_complete_data(tmp_path):
    result = overview("\n".join(f"def f{i}():\n    return {i}" for i in range(25)))
    paths = write_reports(result, tmp_path, ReportFormat.ALL)
    assert [p.suffix for p in paths] == [".md", ".json", ".html"]
    markdown, data, html = (
        paths[0].read_text(),
        json.loads(paths[1].read_text()),
        paths[2].read_text(),
    )
    assert data["metrics_version"] == 2 and data["complete"]
    assert len(data["functions"]) == 25
    assert "maintainability_index" not in data["functions"][0]
    assert "Showing up to 20 of 25" in markdown
    assert "example.py:49 · f24" in html
    assert 'id="chart-0"' in html and 'id="chart-2"' in html
    assert not re.search(r"<script\b[^>]*\bsrc=", html)
    assert "plotly.js" in html  # bundled locally, no CDN dependency


def test_default_is_markdown_without_plotly(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def no_plotly(name, *args, **kwargs):
        if name.startswith("plotly"):
            raise ImportError("optional dependency absent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_plotly)
    assert write_reports(overview(), tmp_path)[0].suffix == ".md"
    assert write_reports(overview(), tmp_path, ReportFormat.JSON)[0].suffix == ".json"
    with pytest.raises(ReportError, match=r"reducio\[reports\]"):
        html_report(overview())


def test_untrusted_paths_and_diagnostics_are_escaped():
    result = overview("def broken(:", "<script>alert(1)</script>|bad.py")
    for report in (html_report(result), markdown_report(result)):
        assert "INCOMPLETE" in report
        assert "Unavailable measurements" in report
        assert "<script>alert(1)</script>" not in report
        assert "&lt;script&gt;" in report


def test_empty_comparison_is_valid_dashboard(tmp_path):
    empty = analyze_files([], AppConfig())
    result = CompareResult(base_revision="base", head_revision="head", before=empty, after=empty)
    assert "No Python changes" in markdown_report(result)
    html = html_report(result)
    assert "No comparable function measurements" in html
    assert 'id="chart-3"' in html
    assert "Complete" in html


def test_cli_analyze_all_and_partial_failure(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "ok.py").write_text("def f():\n    return 1\n")
    output = tmp_path / "reports"
    runner = CliRunner()
    args = ["analyze", str(source), "--report", "--format", "all", "--output-dir", str(output)]
    success = runner.invoke(app, args)
    assert success.exit_code == 0, success.output
    assert len(list(output.iterdir())) == 3
    (source / "bad.py").write_text("def broken(:")
    failure = runner.invoke(app, args)
    assert failure.exit_code == 1
    assert "Metrics unavailable" in failure.output
    data = json.loads(sorted(output.glob("*.json"))[-1].read_text())
    assert not data["complete"] and len(data["functions"]) == 1


def test_cli_compare_invalid_ref_still_reports(temp_git_repo, tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "compare",
            str(temp_git_repo),
            "--base",
            "no-such-ref",
            "--report",
            "--format",
            "all",
            "--output-dir",
            str(tmp_path / "reports"),
        ],
    )
    assert result.exit_code == 1, result.output
    data = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    assert not data["complete"] and data["diagnostics"]
    assert "No Python changes" not in next((tmp_path / "reports").glob("*.md")).read_text()
    assert len(list((tmp_path / "reports").iterdir())) == 3


def test_cli_compare_is_informational_and_formats_agree(temp_git_repo, tmp_path):
    import subprocess

    def git(*args):
        return subprocess.check_output(["git", "-C", str(temp_git_repo), *args], text=True).strip()

    (temp_git_repo / "main.py").write_text("def f(x):\n    return x\n")
    git("add", "main.py")
    git("commit", "-m", "before")
    base = git("rev-parse", "HEAD")
    (temp_git_repo / "main.py").write_text("def f(x):\n    if x:\n        return x\n    return 0\n")
    git("add", "main.py")
    git("commit", "-m", "after")
    output = tmp_path / "reports"
    result = CliRunner().invoke(
        app,
        [
            "compare",
            str(temp_git_repo),
            "--base",
            base,
            "--head",
            "HEAD",
            "-v",
            "--report",
            "--format",
            "all",
            "--output-dir",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Regressed: 1" in result.output and "CC delta=1" in result.output
    data = json.loads(next(output.glob("*.json")).read_text())
    assert data["counts"]["regressed"] == 1 and data["changes"][0]["cyclomatic_delta"] == 1
    assert "+1" in next(output.glob("*.md")).read_text()
    html = next(output.glob("*.html")).read_text()
    assert "regressed" in html and "1 → 2" in html
    assert 'id="chart-3"' in html


def test_cli_report_write_error_is_nonzero(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    output = tmp_path / "not-a-directory"
    output.write_text("preserve")
    result = CliRunner().invoke(
        app, ["analyze", str(source), "--report", "--output-dir", str(output)]
    )
    assert result.exit_code == 1 and "Report failed" in result.output
    assert output.read_text() == "preserve"


def test_fixture_corpus_reports_known_parse_failures(fixture_files):
    result = analyze_files(fixture_files, AppConfig())
    assert not result.complete and len(result.diagnostics) == 5
    assert result.functions and result.hotspots
    bad_files = {d.file for d in result.diagnostics}
    assert all(f.file not in bad_files for f in result.functions)
