"""Base agent class."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from reducio.models import FileChange, PlanDiagnostic, PlanningProvenance, RefactorPlan
from reducio.plan_review import validate_plan
from reducio.session import SessionStore
from reducio.utils.code_utils import strip_code_fence
from reducio.workspace import Workspace

if TYPE_CHECKING:
    from reducio.llm.router import LLMClient


class ModelRewriteError(RuntimeError):
    pass


class BaseAgent:
    def __init__(
        self,
        workspace: Workspace | None = None,
        llm_router: LLMClient | None = None,
        session_store: SessionStore | None = None,
    ):
        self.workspace = workspace
        self.llm = llm_router
        self.session_store = session_store or SessionStore(
            str(workspace.root / ".reducio" / "sessions") if workspace else ".reducio/sessions"
        )
        self._begin_plan()

    def _begin_plan(self, allow_fallback: bool = False) -> None:
        self.allow_fallback = allow_fallback
        self.diagnostics: list[PlanDiagnostic] = []
        self.provenance: list[PlanningProvenance] = []

    def _generate_session_id(self) -> str:
        return str(uuid.uuid4())

    def _save_plan(self, plan: RefactorPlan, command_type: str) -> None:
        self.session_store.save_plan(plan, command_type=command_type)

    def get_plan(self, session_id: str) -> RefactorPlan | None:
        return self.session_store.load_plan(session_id)

    def _file_content_path(self, file) -> tuple[str, str]:
        if hasattr(file, "content"):
            return file.content, file.path
        return file["content"], file["path"]

    def _llm_enabled(self) -> bool:
        # An explicit model request must not silently degrade when no router is wired.
        return bool(
            self.workspace
            and (
                self.workspace.cfg.model
                or self.workspace.cfg.llm_api
                or self.workspace.cfg.llm_base_url
            )
        )

    async def _llm_rewrite(
        self, content: str, path: str, instruction: str, description: str
    ) -> FileChange | None:
        """Ask the LLM to rewrite a whole module; returns a reviewable change or None."""
        prompt = (
            f"{instruction}\nReturn ONLY the complete rewritten module, no prose.\n\n"
            f"```python\n{content}\n```"
        )
        model = self.workspace.cfg.model if self.workspace else ""
        model = "custom endpoint" if "://" in model else model
        try:
            if self.llm is None:
                raise ModelRewriteError("No model router available")
            raw = await self.llm.complete(
                prompt, system_prompt="You are an expert Python engineer."
            )
            code = strip_code_fence(raw)
            if not code.strip():
                raise ValueError("Empty model response")
            compile(code, path, "exec")
        except Exception as error:
            from reducio.llm.router import LLMError

            detail = f": {error}" if isinstance(error, LLMError) else ""
            self.diagnostics.append(
                PlanDiagnostic(
                    code="model_failed",
                    file=path,
                    message="Model rewrite failed or returned empty/invalid Python"
                    + detail
                    + (
                        "; explicit fallback enabled"
                        if self.allow_fallback
                        else "; no application permitted"
                    ),
                    severity="warning" if self.allow_fallback else "error",
                )
            )
            self.provenance.append(
                PlanningProvenance(file=path, engine="model", outcome="failed", model=model)
            )
            raise ModelRewriteError("Model rewrite unavailable") from None
        self.provenance.append(
            PlanningProvenance(
                file=path,
                engine="model",
                outcome="unchanged" if code.strip() == content.strip() else "proposed",
                model=model,
            )
        )
        if code.strip() == content.strip():
            return None
        return FileChange(
            path=path,
            original=content,
            modified=code if code.endswith("\n") else code + "\n",
            description=description,
        )

    def _finalize_plan(
        self, changes: list, description: str, command_type: str, **plan_kw
    ) -> RefactorPlan:
        plan = RefactorPlan(
            session_id=self._generate_session_id(),
            changes=changes,
            description=description,
            diagnostics=self.diagnostics,
            provenance=self.provenance,
            **plan_kw,
        )
        # Coalesce truly identical changes, but never silently pick one conflicting version.
        unique = []
        for change in plan.changes:
            if change not in unique:
                unique.append(change)
        plan.changes = unique
        plan.diagnostics.extend(
            validate_plan(plan, self.workspace.root if self.workspace else None)
        )
        plan.complete = not any(item.severity == "error" for item in plan.diagnostics)
        self._save_plan(plan, command_type)
        return plan
