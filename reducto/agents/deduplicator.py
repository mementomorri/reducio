"""Deduplicator agent — semantic duplicate detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reducto.agents.base import BaseAgent

if TYPE_CHECKING:
    from reducto.embeddings.service import EmbeddingService
from reducto.models import (
    CodeBlock,
    DeduplicateRequest,
    FileChange,
    FileInfo,
    Language,
    RefactorPlan,
)
from reducto.parse import get_complexity
from reducto.repo import detect_language
from reducto.session import SessionStore
from reducto.workspace import Workspace


class DeduplicatorAgent(BaseAgent):
    workspace: Workspace

    def __init__(
        self,
        workspace: Workspace,
        embedding_service: EmbeddingService,
        llm_router=None,
        session_store: SessionStore | None = None,
    ):
        super().__init__(workspace, llm_router, session_store)
        self.embedding_service = embedding_service

    async def find_duplicates(self, request: DeduplicateRequest) -> RefactorPlan:
        files = request.files or self.workspace.list_files()
        if not self.embedding_service.is_using_real_embeddings:
            return self._finalize_plan(
                [],
                "Semantic embeddings unavailable — install the extra "
                "(pip install -e '.[embeddings]'); no duplicates analyzed.",
                "deduplicate",
            )
        blocks = self._extract_blocks(files)
        groups = await self.embedding_service.find_duplicates(blocks, request.similarity_threshold)
        changes = []
        for group in groups:
            if len(group) >= 2:
                ch = self._create_dedup_change(group)
                if ch:
                    changes.append(ch)
        return self._finalize_plan(
            changes,
            f"Found {len(groups)} duplicate group(s); proposing {len(changes)} shared-util "
            "suggestion(s) (review before adopting — call sites are not rewritten).",
            "deduplicate",
        )

    def _extract_blocks(self, files: list[FileInfo]) -> list[CodeBlock]:
        blocks: list[CodeBlock] = []
        for f in files:
            lang = detect_language(f.path)
            if lang == Language.UNKNOWN:
                continue
            for sym in self.workspace.get_symbols(f.path, f.content):
                if sym.type not in ("function", "method"):
                    continue
                lines = f.content.split("\n")
                end = min(sym.end_line, len(lines))
                content = "\n".join(lines[sym.start_line - 1 : end])
                try:
                    metrics = get_complexity(content)
                except SyntaxError, ValueError:
                    continue  # invalid snippets have no trustworthy numeric score
                blocks.append(
                    CodeBlock(
                        id=f"{f.path}:{sym.start_line}:{sym.name}",
                        file=f.path,
                        start_line=sym.start_line,
                        end_line=end,
                        content=content,
                        language=lang,
                        symbol_type=sym.type,
                        symbol_name=sym.name,
                        metrics=metrics,
                    )
                )
        return blocks

    def _create_dedup_change(self, group: list[CodeBlock]) -> FileChange | None:
        primary = group[0]
        return FileChange(
            path=f"utils/{primary.symbol_name}_dedup.py",
            original="",
            modified=primary.content,
            description=(
                f"Proposed shared util for '{primary.symbol_name}' from {len(group)} sites "
                "(suggestion only; applying writes the utility module; "
                "originals and call sites are not rewritten)"
            ),
        )
