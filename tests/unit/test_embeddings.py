"""Embedding service tests."""

from unittest.mock import AsyncMock

import pytest

from reducio.embeddings.service import EmbeddingService
from reducio.models import CodeBlock, ComplexityMetrics, Language


@pytest.mark.asyncio
async def test_find_duplicates_without_real_embeddings_returns_empty():
    svc = EmbeddingService()
    svc._initialized = True
    svc._use_real_embeddings = False
    blocks = [
        CodeBlock(
            id="1",
            file="a.py",
            start_line=1,
            end_line=2,
            content="def a(): pass",
            language=Language.PYTHON,
            symbol_type="function",
            symbol_name="a",
            metrics=ComplexityMetrics(),
        )
    ]
    groups = await svc.find_duplicates(blocks, threshold=0.85)
    assert groups == []


@pytest.mark.asyncio
async def test_find_duplicates_groups_with_mock_similarity():
    svc = EmbeddingService()
    svc._initialized = True
    svc._use_real_embeddings = True
    blocks = [
        CodeBlock(
            id="a",
            file="a.py",
            start_line=1,
            end_line=2,
            content="def a(): pass",
            language=Language.PYTHON,
            symbol_type="function",
            symbol_name="a",
            metrics=ComplexityMetrics(),
            embedding=[0.1] * 8,
        ),
        CodeBlock(
            id="b",
            file="b.py",
            start_line=1,
            end_line=2,
            content="def b(): pass",
            language=Language.PYTHON,
            symbol_type="function",
            symbol_name="b",
            metrics=ComplexityMetrics(),
            embedding=[0.2] * 8,
        ),
    ]
    svc.embed_blocks = AsyncMock(return_value=blocks)
    svc.store_embeddings = AsyncMock()
    svc.find_similar = AsyncMock(return_value=[{"id": "b", "distance": 0.05}])

    groups = await svc.find_duplicates(blocks, threshold=0.85)
    assert len(groups) == 1
    assert len(groups[0]) == 2
