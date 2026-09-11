"""AnalyzerAgent hotspot detection and language filtering."""

import pytest

from reducio.agents.analyzer import AnalyzerAgent
from reducio.models import AnalyzeRequest, AppConfig, FileInfo
from reducio.workspace import Workspace


def _ws(tmp_path, threshold: int) -> Workspace:
    cfg = AppConfig()
    cfg.complexity_thresholds.cyclomatic_complexity = threshold
    return Workspace(str(tmp_path), cfg)


async def _analyze(ws, code: str, path: str = "f.py"):
    return await AnalyzerAgent(ws).analyze(
        AnalyzeRequest(path=str(ws.root), files=[FileInfo(path=path, content=code)])
    )


@pytest.mark.asyncio
async def test_hotspot_detected_above_threshold(tmp_path):
    code = "def f(a):\n    if a:\n        if a:\n            if a:\n                return 1\n    return 0\n"
    res = await _analyze(_ws(tmp_path, 2), code)
    assert res.total_symbols >= 1
    assert len(res.hotspots) == 1
    assert res.hotspots[0].symbol == "f"


@pytest.mark.asyncio
async def test_no_hotspot_below_threshold(tmp_path):
    code = "def f(a):\n    if a:\n        return 1\n    return 0\n"
    res = await _analyze(_ws(tmp_path, 100), code)
    assert res.hotspots == []


@pytest.mark.asyncio
async def test_analyze_skips_unknown_language(tmp_path):
    res = await _analyze(_ws(tmp_path, 1), "hello world\n", path="notes.txt")
    assert res.total_symbols == 0
