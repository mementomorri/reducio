"""Characterization tests for DeduplicatorAgent (suggest-only stub plans)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from reducto.agents.deduplicator import DeduplicatorAgent
from reducto.models import (
    CodeBlock,
    ComplexityMetrics,
    DeduplicateRequest,
    FileInfo,
    Language,
)
from reducto.workspace import Workspace


@pytest.mark.asyncio
async def test_dedup_plan_uses_utils_stub_path(tmp_path):
    block = CodeBlock(
        id="a.py:1:validate_email",
        file="a.py",
        start_line=1,
        end_line=3,
        content="def validate_email(e):\n    return '@' in e\n",
        language=Language.PYTHON,
        symbol_type="function",
        symbol_name="validate_email",
        metrics=ComplexityMetrics(),
        embedding=[0.1] * 384,
    )
    emb = MagicMock()
    emb.find_duplicates = AsyncMock(return_value=[[block, block]])
    ws = Workspace(str(tmp_path))
    agent = DeduplicatorAgent(ws, emb)
    plan = await agent.find_duplicates(
        DeduplicateRequest(path=str(tmp_path), files=[FileInfo(path="a.py", content=block.content)])
    )
    assert plan.changes
    from reducto.plan_review import advisory_path

    assert plan.changes[0].path == advisory_path("utils", "a.py", "validate_email_1_dedup")
    assert plan.changes[0].original == ""
    # P1: honest labeling — it suggests, it does not rewrite call sites.
    assert "suggestion only" in plan.changes[0].description
    assert "not rewritten" in plan.description


@pytest.mark.asyncio
async def test_dedup_warns_when_embeddings_unavailable(tmp_path):
    emb = MagicMock()
    emb.is_using_real_embeddings = False  # extra not installed / model failed to load
    agent = DeduplicatorAgent(Workspace(str(tmp_path)), emb)
    plan = await agent.find_duplicates(DeduplicateRequest(path=str(tmp_path), files=[]))
    assert plan.changes == []
    assert "embeddings" in plan.description.lower()
