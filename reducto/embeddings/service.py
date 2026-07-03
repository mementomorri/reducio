"""
Embedding service for semantic code analysis.
"""

import hashlib
import logging
from typing import Any, cast

from reducto.models import CodeBlock, FileInfo

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        self.client: Any = None
        self.collection = None
        self.model: Any = None
        self._initialized = False
        self._use_real_embeddings: bool = False

    async def initialize(self, verbose: bool = False):
        if self._initialized:
            return

        try:
            import os

            if not verbose:
                os.environ["TOKENIZERS_PARALLELISM"] = "false"
                os.environ["TRANSFORMERS_VERBOSITY"] = "error"
                os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
                os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

            import logging as st_logging

            from sentence_transformers import SentenceTransformer

            st_logging.getLogger("sentence_transformers").setLevel(st_logging.ERROR)
            st_logging.getLogger("transformers").setLevel(st_logging.ERROR)
            st_logging.getLogger("huggingface_hub").setLevel(st_logging.ERROR)

            self.model = SentenceTransformer("all-MiniLM-L6-v2")
            self._use_real_embeddings = True
            logger.info(
                "Loaded sentence-transformers model: all-MiniLM-L6-v2 for semantic embeddings"
            )
        except ImportError:
            logger.warning(
                "sentence-transformers not available. Semantic deduplication will not work correctly."
            )
            logger.warning("Install with: pip install sentence-transformers")
            self._use_real_embeddings = False
        except Exception as e:
            logger.warning(
                f"Failed to load sentence-transformers: {e}. Semantic deduplication will not work correctly."
            )
            self._use_real_embeddings = False

        # chromadb is part of the [embeddings] extra; if it's absent, degrade to the
        # "install the extra" path instead of crashing at import time.
        try:
            import chromadb

            self.client = chromadb.EphemeralClient()
            self.collection = self.client.get_or_create_collection(
                name="code_embeddings", metadata={"hnsw:space": "cosine"}
            )
        except ImportError:
            self._use_real_embeddings = False

        self._initialized = True

    async def shutdown(self):
        if self.client:
            self.client = None
            self.collection = None
            self.model = None
            self._initialized = False
            self._use_real_embeddings = False

    def _mock_embedding(self, text: str) -> list[float]:
        """Generate deterministic mock embedding using hash.

        WARNING: This is NOT semantic similarity - it's just for testing.
        Hash-based embeddings will NOT detect semantically similar code blocks.
        """
        h = hashlib.sha256(text.encode()).hexdigest()
        embedding = []
        # Generate 384 dimensions by reusing hash bytes
        for i in range(384):
            idx = (i * 2) % len(h)
            val = int(h[idx : idx + 2], 16) / 255.0
            embedding.append(val)
        return embedding

    async def embed_text(self, text: str) -> list[float]:
        if self._use_real_embeddings and self.model:
            embedding = self.model.encode(text, convert_to_numpy=True)
            return cast(list[float], embedding.tolist())
        else:
            return self._mock_embedding(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._use_real_embeddings and self.model:
            embeddings = self.model.encode(texts, convert_to_numpy=True)
            return cast(list[list[float]], embeddings.tolist())
        else:
            return [self._mock_embedding(t) for t in texts]

    async def embed_files(self, files: list[FileInfo]) -> dict[str, list[float]]:
        if not files:
            return {}

        texts = [f.content for f in files]
        embeddings = await self.embed_batch(texts)
        return {f.path: emb for f, emb in zip(files, embeddings)}

    async def embed_blocks(self, blocks: list[CodeBlock]) -> list[CodeBlock]:
        if not blocks:
            return blocks

        texts = [block.content for block in blocks]
        embeddings = await self.embed_batch(texts)

        for block, embedding in zip(blocks, embeddings):
            block.embedding = embedding

        return blocks

    async def store_embeddings(self, blocks: list[CodeBlock]):
        if not self._initialized or not self.collection:
            return

        ids = [block.id for block in blocks]
        embeddings = [block.embedding for block in blocks if block.embedding]
        metadatas = [
            {
                "file": block.file,
                "start_line": block.start_line,
                "end_line": block.end_line,
                "symbol_type": block.symbol_type,
                "symbol_name": block.symbol_name,
                "language": block.language.value,
            }
            for block in blocks
        ]
        documents = [block.content for block in blocks]

        if embeddings:
            self.collection.add(
                ids=ids[: len(embeddings)],
                embeddings=embeddings,
                metadatas=metadatas[: len(embeddings)],
                documents=documents[: len(embeddings)],
            )

    async def find_similar(
        self,
        embedding: list[float],
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        if not self._initialized or not self.collection:
            return []

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
        )

        similar = []
        for i, id in enumerate(results["ids"][0]):
            similar.append(
                {
                    "id": id,
                    "distance": results["distances"][0][i] if results.get("distances") else 0,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "content": results["documents"][0][i] if results.get("documents") else "",
                }
            )

        return similar

    async def find_duplicates(
        self,
        blocks: list[CodeBlock],
        threshold: float = 0.85,
    ) -> list[list[CodeBlock]]:
        if not self._initialized:
            await self.initialize()

        if not self._use_real_embeddings:
            logger.warning("Using hash-based embeddings - semantic deduplication is disabled.")
            logger.warning(
                "Install sentence-transformers for semantic duplicate detection: pip install sentence-transformers"
            )
            return []

        blocks_with_embeddings = await self.embed_blocks(blocks)
        await self.store_embeddings(blocks_with_embeddings)

        groups = []
        processed = set()
        by_id = {b.id: b for b in blocks_with_embeddings}

        for block in blocks_with_embeddings:
            if block.id in processed or not block.embedding:
                continue

            similar = await self.find_similar(block.embedding, n_results=10)
            group = [block]
            processed.add(block.id)

            for sim in similar:
                if sim["id"] == block.id:
                    continue
                if 1 - sim["distance"] < threshold:
                    continue
                other = by_id.get(sim["id"])
                if other and other.id not in processed:
                    group.append(other)
                    processed.add(other.id)

            if len(group) > 1:
                groups.append(group)

        return groups

    async def clear(self):
        if self._initialized and self.client:
            self.client.delete_collection("code_embeddings")
            self.collection = self.client.get_or_create_collection(
                name="code_embeddings", metadata={"hnsw:space": "cosine"}
            )

    @property
    def is_using_real_embeddings(self) -> bool:
        return self._use_real_embeddings
