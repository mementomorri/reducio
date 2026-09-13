"""Semantic grouping contracts with fake model vectors; no downloads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from reducio.embeddings.service import EmbeddingService
from reducio.models import CodeBlock, ComplexityMetrics, Language


def blocks(count):
    return [
        CodeBlock(
            id=str(i),
            file=f"f{i:03}.py",
            start_line=1,
            end_line=2,
            content=f"function {i}",
            language=Language.PYTHON,
            symbol_type="function",
            symbol_name="f",
            metrics=ComplexityMetrics(),
        )
        for i in range(count)
    ]


async def test_unavailable_embeddings_fail_explicitly():
    service = EmbeddingService()
    assert not service.is_using_real_embeddings
    with pytest.raises(ValueError, match="initialized"):
        await service.find_duplicates(blocks(2))


async def test_large_groups_deterministic_across_runs():
    service = EmbeddingService()
    service.embed_batch = AsyncMock(return_value=[[1.0, 0.0]] * 260)
    items = blocks(260)
    first = await service.find_duplicates(items)
    assert len(first) == 1 and len(first[0]) == 260
    assert await service.find_duplicates(items[::-1]) == first
    assert await service.find_duplicates(items) == first


async def test_no_transitive_merging():
    service = EmbeddingService()
    # A~B, B~C, but A is not similar to C.
    service.embed_batch = AsyncMock(return_value=[[1.0, 0.0], [0.9, 0.43589], [0.62, 0.7846]])
    groups = await service.find_duplicates(blocks(3))
    assert [[b.id for b in g] for g in groups] == [["0", "1"]]


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[1.0]],
        [[1.0], [1.0, 2.0]],
        [[0.0, 0.0], [1.0, 0.0]],
        [[float("nan")], [1.0]],
        [[float("inf")], [1.0]],
        [[], []],
    ],
)
async def test_invalid_vectors_rejected(vectors):
    service = EmbeddingService()
    service.embed_batch = AsyncMock(return_value=vectors)
    with pytest.raises(ValueError):
        await service.find_duplicates(blocks(2))


@pytest.mark.parametrize("threshold", [-1, 2, float("nan"), float("inf")])
async def test_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        await EmbeddingService().find_duplicates([], threshold)


async def test_empty_and_duplicate_ids():
    service = EmbeddingService()
    assert await service.find_duplicates([]) == []
    item = blocks(1)[0]
    with pytest.raises(ValueError, match="identifiers"):
        await service.find_duplicates([item, item])


async def test_model_lifecycle_and_batch(monkeypatch):
    import sys

    model = SimpleNamespace(encode=lambda texts, **kw: np.ones((len(texts), 2)))
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=lambda name: model),
    )
    service = EmbeddingService()
    await service.initialize()
    await service.initialize()
    assert service.is_using_real_embeddings
    assert await service.embed_text("source") == [1.0, 1.0]
    assert await service.embed_batch([]) == []
    await service.shutdown()
    assert not service.is_using_real_embeddings


async def test_model_load_failure(monkeypatch):
    import sys

    def unavailable(*a, **kw):
        raise RuntimeError("private details")

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=unavailable)
    )
    service = EmbeddingService()
    await service.initialize()
    assert not service.is_using_real_embeddings
