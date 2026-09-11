"""Characterization tests for QualityCheckerAgent."""

import pytest

from reducio.agents.quality_checker import QualityCheckerAgent
from reducio.models import FileInfo, Language


def _long_python_body() -> str:
    lines = ["def long_runner():"]
    lines.extend([f"    x = {i}" for i in range(55)])
    lines.append("    return x")
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_check_quality_flags_long_function():
    content = _long_python_body()
    agent = QualityCheckerAgent()
    report = await agent.check_quality(
        [FileInfo(path="sample.py", content=content)],
        path=".",
    )
    long_fn = [i for i in report.issues if i.issue_type == "long_function"]
    assert long_fn
    assert long_fn[0].line == 1
    assert long_fn[0].symbol == "long_runner"


@pytest.mark.asyncio
async def test_check_quality_flags_bad_variable_name():
    content = "def f():\n    qq = 1\n    return qq\n"
    agent = QualityCheckerAgent()
    report = await agent.check_quality(
        [FileInfo(path="sample.py", content=content)],
        path=".",
    )
    bad = [i for i in report.issues if i.issue_type == "bad_variable_name"]
    assert bad
    assert any(i.symbol == "qq" for i in bad)


@pytest.mark.asyncio
async def test_check_flags_high_complexity_function():
    body = "\n".join(f"    if x{i}:\n        return {i}" for i in range(12))
    content = f"def busy(x0):\n{body}\n    return 0\n"
    report = await QualityCheckerAgent().check_quality(
        [FileInfo(path="hc.py", content=content)], path="."
    )
    cc = [i for i in report.issues if i.issue_type == "high_complexity_function"]
    assert cc
    assert cc[0].symbol == "busy"
    assert cc[0].severity in ("critical", "warning")


@pytest.mark.asyncio
async def test_check_uses_config_thresholds(tmp_path):
    from reducio.models import AppConfig
    from reducio.workspace import Workspace

    cfg = AppConfig()
    cfg.complexity_thresholds.cyclomatic_complexity = 2
    agent = QualityCheckerAgent(Workspace(str(tmp_path), cfg))
    content = "def f(a):\n    if a:\n        return 1\n    if a:\n        return 2\n"
    report = await agent.check_quality([FileInfo(path="f.py", content=content)], path=".")
    assert any(i.issue_type == "high_complexity_function" for i in report.issues)


def test_detect_language_via_repo():
    from reducio.repo import detect_language

    assert detect_language("a.py") == Language.PYTHON
    assert detect_language("b.js") == Language.UNKNOWN
