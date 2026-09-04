"""Reporter markdown generation and loading."""

import pytest

from reducto.models import (
    AnalyzeResult,
    ComplexityHotspot,
    ComplexityMetrics,
    FileChange,
    RefactorPlan,
    RefactorResult,
)
from reducto.reporter import Reporter


def test_generate_baseline_with_hotspots(tmp_path):
    hs = ComplexityHotspot(
        file="a.py", line=1, symbol="f", cyclomatic_complexity=12, cognitive_complexity=7
    )
    path = Reporter(output_dir=str(tmp_path / ".reducto")).generate_baseline(
        AnalyzeResult(total_files=1, total_symbols=3, hotspots=[hs], symbols=[])
    )
    text = path.read_text()
    assert "Complexity Hotspots" in text
    assert "Cognitive" in text
    assert "f" in text and "12" in text and "7" in text
    assert "cyclomatic complexity" in text.lower()


def test_generate_check_writes_issues(tmp_path):
    path = Reporter(output_dir=str(tmp_path / ".reducto")).generate_check(
        {
            "total_issues": 1,
            "critical": 1,
            "warning": 0,
            "info": 0,
            "issues": [
                {
                    "file": "a.py",
                    "line": 10,
                    "issue_type": "long_function",
                    "severity": "critical",
                    "message": "Function 'f' is 120 lines (max 50)",
                    "symbol": "f",
                    "suggestion": "split | extract",
                }
            ],
        }
    )
    text = path.read_text()
    assert "long_function" in text
    assert "a.py" in text
    assert "split / extract" in text
    assert path.name.startswith("reducto-check-")


def test_generate_check_empty(tmp_path):
    path = Reporter(output_dir=str(tmp_path / ".reducto")).generate_check(
        {"total_issues": 0, "critical": 0, "warning": 0, "info": 0, "issues": []}
    )
    text = path.read_text()
    assert "| Total Issues | 0 |" in text
    assert "## Issues" not in text


def test_generate_dry_run(tmp_path):
    plan = RefactorPlan(
        session_id="abcd1234ef",
        changes=[FileChange(path="x.py", original="", modified="y", description="do x")],
        description="plan",
    )
    out = Reporter(output_dir=str(tmp_path / ".reducto")).generate_dry_run(plan, "idiomatize", "p")
    text = out.read_text()
    assert "Dry Run: idiomatize" in text
    assert "x.py" in text


def test_generate_report(tmp_path):
    res = RefactorResult(
        session_id="sess1",
        success=True,
        changes=[],
        tests_passed=True,
        metrics_before=ComplexityMetrics(lines_of_code=10),
        metrics_after=ComplexityMetrics(lines_of_code=4),
    )
    out = Reporter(output_dir=str(tmp_path / ".reducto")).generate(res)
    text = out.read_text()
    assert "Reduced: 6" in text
    assert "Success: True" in text


def test_load_latest_roundtrip(tmp_path):
    reporter = Reporter(output_dir=str(tmp_path / ".reducto"))
    reporter.generate(
        RefactorResult(session_id="sess1", success=True, changes=[], tests_passed=True)
    )
    assert "reducto Report" in reporter.load_latest()
    with pytest.raises(FileNotFoundError):
        reporter.load_latest("nope")
