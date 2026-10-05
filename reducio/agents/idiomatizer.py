"""Idiomatizer agent: model-proposed idiomatic rewrites of Python modules."""

from reducio.agents.base import BaseAgent, ModelRewriteError
from reducio.models import FileInfo, IdiomatizeRequest, Language, PlanDiagnostic, RefactorPlan
from reducio.repo import detect_language


class IdiomatizerAgent(BaseAgent):
    def idiomatize(self, request: IdiomatizeRequest) -> RefactorPlan:
        self._begin_plan()
        changes = []
        for file in request.files:
            if not file.error and detect_language(file.path) != Language.PYTHON:
                continue
            try:
                if change := self._idiomatize_file(file):
                    changes.append(change)
            except ModelRewriteError:
                break  # diagnostics record the failure; the plan is incomplete
        return self._finalize_plan(
            changes,
            f"Proposed idiomatic rewrites for {len(changes)} file(s).",
            "idiomatize",
        )

    def _idiomatize_file(self, file: FileInfo):
        try:
            file.tree  # Validated once, shared with subsequent analysis.
        except SyntaxError, ValueError:
            self.diagnostics.append(
                PlanDiagnostic(
                    code="invalid_source",
                    file=file.path,
                    severity="error",
                    message="Cannot read or parse source; planning incomplete",
                )
            )
            return None
        change = self._llm_rewrite(
            file.content,
            file.path,
            "Rewrite the following Python module to be more idiomatic and concise without changing behaviour.",
            "LLM idiomatic rewrite",
        )
        if change:
            change.operation, change.encoding = "replace", file.encoding
        return change
