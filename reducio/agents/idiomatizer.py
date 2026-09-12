"""
Idiomatizer agent for transforming code to idiomatic patterns (Python heuristics).
"""

import ast

from reducio.agents.base import BaseAgent, ModelRewriteError
from reducio.models import (
    FileChange,
    IdiomatizeRequest,
    Language,
    PlanDiagnostic,
    PlanningProvenance,
    RefactorPlan,
)
from reducio.repo import detect_language
from reducio.session import SessionStore


class IdiomatizerAgent(BaseAgent):
    def __init__(self, workspace=None, llm_router=None, session_store: SessionStore | None = None):
        super().__init__(workspace, llm_router, session_store)

    async def idiomatize(self, request: IdiomatizeRequest) -> RefactorPlan:
        self._begin_plan(request.allow_fallback)
        changes = []
        idioms = 0
        for file in request.files:
            try:
                change, count = await self._idiomatize_file(file)
            except ModelRewriteError:
                break
            if change:
                changes.append(change)
                idioms += count
        return self._finalize_plan(
            changes,
            f"Found {idioms} opportunities for idiomatic improvements in {len(changes)} file(s).",
            "idiomatize",
        )

    async def _idiomatize_file(self, file) -> tuple[FileChange | None, int]:
        content, path = self._file_content_path(file)
        if detect_language(path) != Language.PYTHON:
            return None, 0
        try:
            ast.parse(content)  # can't safely rewrite (or validate) a file that doesn't parse
        except SyntaxError:
            self.diagnostics.append(
                PlanDiagnostic(
                    code="invalid_source", file=path, message="Skipped invalid Python source"
                )
            )
            return None, 0
        if self._llm_enabled():
            try:
                change = await self._llm_rewrite(
                    content,
                    path,
                    "Rewrite the following Python module to be more idiomatic and concise without changing behaviour.",
                    "LLM idiomatic rewrite",
                )
                return change, int(change is not None)
            except ModelRewriteError:
                if not self.allow_fallback:
                    raise
        change, count = self._idiomatize_python(content, path)
        self.provenance.append(
            PlanningProvenance(
                file=path, engine="heuristic", outcome="proposed" if change else "unchanged"
            )
        )
        return change, count

    def _idiomatize_python(self, content: str, path: str) -> tuple[FileChange | None, int]:
        from reducio.idioms import rewrite

        updated, descriptions, diagnostics = rewrite(content, path)
        self.diagnostics.extend(diagnostics)
        if updated == content:
            return None, 0
        return FileChange(
            path=path, original=content, modified=updated, description="; ".join(descriptions)
        ), len(descriptions)
