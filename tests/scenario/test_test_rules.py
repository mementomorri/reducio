"""Automated coverage for docs/TEST_RULES.md scenarios."""

from pathlib import Path

from reducio.agents.analyzer import AnalyzerAgent
from reducio.agents.deduplicator import DeduplicatorAgent
from reducio.agents.pattern import PatternAgent
from reducio.models import (
    AnalyzeRequest,
    DeduplicateRequest,
    FileInfo,
    Language,
    PatternRequest,
)
from reducio.repo import detect_language
from reducio.visual_report import write_reports
from reducio.workspace import Workspace

FIXTURE = Path(__file__).resolve().parents[2] / "test-python-code" / "python"


def test_repo_detects_python_only(fixture_files):
    langs = {detect_language(f.path) for f in fixture_files}
    assert langs == {Language.PYTHON}


def test_analyze_returns_symbols(fixture_files):
    ws = Workspace(str(FIXTURE.parent.parent))
    result = AnalyzerAgent(ws).analyze(AnalyzeRequest(path=str(FIXTURE), files=fixture_files))
    assert result.total_symbols > 0


def test_analyze_returns_symbols_and_hotspots(fixture_files):
    # Regression for the parser-shadow bug: high_complexity.py guarantees a hotspot
    # once symbol extraction works (default CC threshold = 10).
    ws = Workspace(str(FIXTURE))
    result = AnalyzerAgent(ws).analyze(AnalyzeRequest(path=str(FIXTURE), files=fixture_files))
    assert result.total_symbols > 0
    assert len(result.hotspots) > 0


def test_deduplicate_groups_validator_clones(sample_repo):
    # Renamed-identifier clones across both validator modules become suggestions.
    root = sample_repo / "duplicates"
    plan = DeduplicatorAgent(Workspace(str(root))).find_duplicates(
        DeduplicateRequest(path=str(root))
    )
    from reducio.plan_review import advisory_path

    paths = {c.path for c in plan.changes}
    assert advisory_path("utils", "auth_validator.py", "validate_email_address_6_dedup") in paths
    assert len(plan.changes) == 4  # email, password, username, phone pairs
    assert all(c.original == "" and "utils/" in c.path for c in plan.changes)


def test_pattern_strategy_on_complex_conditionals(tmp_path):
    path = FIXTURE / "patterns" / "complex_conditionals.py"
    content = path.read_text(encoding="utf-8")
    plan = PatternAgent(Workspace(str(tmp_path))).apply_pattern(
        PatternRequest(
            pattern="strategy",
            path=str(FIXTURE),
            files=[FileInfo(path=path.name, content=content)],
        )
    )
    assert any("strategies/" in c.path for c in plan.changes)


def test_reporter_writes_markdown(tmp_path):
    from reducio.models import AnalyzeResult

    out = tmp_path / ".reducio"
    [path] = write_reports(AnalyzeResult(total_files=1, total_symbols=2, hotspots=[]), out)
    assert path.exists()
    assert "Baseline" in path.read_text(encoding="utf-8")
