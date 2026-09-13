"""
Idiomatizer agent for transforming code to idiomatic patterns (Python heuristics).
"""

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


class IdiomatizerAgent(BaseAgent):
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
        if not file.error and detect_language(path) != Language.PYTHON:
            return None, 0
        try:
            file.tree  # Validated once, shared with subsequent analysis.
        except SyntaxError, ValueError:
            self.diagnostics.append(
                PlanDiagnostic(
                    code="invalid_source",
                    file=path,
                    severity="error",
                    message="Cannot read or parse source; planning incomplete",
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
                if change:
                    change.operation, change.encoding = "replace", file.encoding
                return change, int(change is not None)
            except ModelRewriteError:
                if not self.allow_fallback:
                    raise
        change, count = self._idiomatize_python(content, path)
        if change:
            change.operation, change.encoding = "replace", file.encoding
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
