"""Run-local semantic suggestions with bounded-memory cosine comparisons."""

import logging
from typing import Any, cast

from reducio.models import CodeBlock

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        self.model: Any = None

    async def initialize(self, verbose: bool = False):
        if self.model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:
            logger.warning(
                "Semantic model unavailable; install reducio[embeddings] and check model access"
            )

    @property
    def is_using_real_embeddings(self) -> bool:
        return self.model is not None

    async def shutdown(self):
        self.model = None

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.model is None:
            raise ValueError("Semantic model is not initialized")
        if not texts:
            return []
        return cast(
            list[list[float]],
            self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False).tolist(),
        )

    async def embed_text(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def find_duplicates(
        self, blocks: list[CodeBlock], threshold: float = 0.85
    ) -> list[list[CodeBlock]]:
        import numpy as np

        if not np.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("Similarity threshold must be between zero and one")
        if not blocks:
            return []
        ordered = sorted(blocks, key=lambda b: (b.file, b.start_line, b.id))
        if len({b.id for b in ordered}) != len(ordered):
            raise ValueError("Duplicate block identifiers")
        vectors = np.asarray(await self.embed_batch([b.content for b in ordered]), dtype=float)
        if (
            vectors.ndim != 2
            or vectors.shape[0] != len(ordered)
            or not vectors.shape[1]
            or not np.isfinite(vectors).all()
        ):
            raise ValueError("Invalid embedding dimensions or values")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(norms).all() or (norms == 0).any():
            raise ValueError("Embedding vectors must have finite nonzero norms")
        vectors /= norms[:, None]
        used = set()
        groups = []
        # A chunk holds at most 128 x N scores; never allocate an N x N matrix.
        for start in range(0, len(ordered), 128):
            scores = vectors[start : start + 128] @ vectors.T
            for offset, row in enumerate(scores):
                representative = start + offset
                if representative in used:
                    continue
                members = [representative] + [
                    int(i)
                    for i in np.flatnonzero(row >= threshold)
                    if i != representative and i not in used
                ]
                used.update(members)
                if len(members) > 1:
                    groups.append([ordered[i] for i in members])
        return groups
