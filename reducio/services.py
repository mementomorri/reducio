"""Application services — wires workspace, agents, and apply logic."""

from __future__ import annotations

import ast
import difflib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reducio.llm import LLMClient

from reducio.agents import (
    AnalyzerAgent,
    DeduplicatorAgent,
    IdiomatizerAgent,
    PatternAgent,
    QualityCheckerAgent,
)
from reducio.config import apply_env, load_config
from reducio.models import (
    AnalyzeRequest,
    AnalyzeResult,
    AppConfig,
    ComplexityMetrics,
    DeduplicateRequest,
    FileInfo,
    IdiomatizeRequest,
    PatternRequest,
    RefactorPlan,
    RefactorResult,
)
from reducio.plan_review import validate_plan
from reducio.progress import status
from reducio.session import SessionStore
from reducio.workspace import Workspace


class App:
    def __init__(self, root: str, cfg: AppConfig | None = None):
        self.cfg = cfg.model_copy(deep=True) if cfg is not None else apply_env(load_config())
        self.root = root
        self.workspace = Workspace(root, self.cfg)
        self.sessions = SessionStore(storage_dir=str(self.workspace.root / ".reducio" / "sessions"))
        self.llm: LLMClient | None = None
        self._embedding = None
        self.analyzer = AnalyzerAgent(self.workspace)
        self.quality = QualityCheckerAgent(self.workspace)

    async def _embeddings(self):
        if self._embedding is None:
            status("Loading embeddings (first use may download a model)...")
            from reducio.embeddings import EmbeddingService

            self._embedding = EmbeddingService()
            await self._embedding.initialize(verbose=self.cfg.verbose)
        return self._embedding

    def _files(self) -> list[FileInfo]:
        return self.workspace.list_files()

    async def analyze(self, path: str) -> AnalyzeResult:
        return await self.analyzer.analyze(AnalyzeRequest(path=path, files=self._files()))

    async def deduplicate(self, path: str) -> RefactorPlan:
        emb = await self._embeddings()
        agent = DeduplicatorAgent(self.workspace, emb, self.llm, self.sessions)
        files = self._files()
        status("Finding similar functions and preparing duplicate proposals...")
        return await agent.find_duplicates(DeduplicateRequest(path=path, files=files))

    async def idiomatize(self, path: str, *, allow_fallback: bool = False) -> RefactorPlan:
        self._prepare_llm()
        agent = IdiomatizerAgent(self.workspace, self.llm, self.sessions)
        files = self._files()
        status("Analyzing idioms and preparing proposals...")
        return await agent.idiomatize(
            IdiomatizeRequest(path=path, files=files, allow_fallback=allow_fallback)
        )

    async def pattern(
        self, pattern_name: str, path: str, *, allow_fallback: bool = False
    ) -> RefactorPlan:
        if pattern_name:
            self._prepare_llm()
        agent = PatternAgent(self.workspace, self.llm, self.sessions)
        files = self._files()
        status("Analyzing patterns and preparing suggestions...")
        return await agent.apply_pattern(
            PatternRequest(
                pattern=pattern_name, path=path, files=files, allow_fallback=allow_fallback
            )
        )

    async def check(self, path: str) -> dict[str, Any]:
        files = self._files()
        status("Checking naming, function length, and complexity...")
        report = await self.quality.check_quality(files, path)
        result = report.to_dict()
        from reducio.quality_gate import evaluate_gate

        result.update(evaluate_gate(result, self.cfg.check_fail_on))
        return result

    def _prepare_llm(self) -> None:
        if self.llm is None and (self.cfg.model or self.cfg.llm_api or self.cfg.llm_base_url):
            from reducio.llm import LLMClient

            self.llm = LLMClient(self.cfg)

    def apply_plan(self, plan: RefactorPlan, run_tests: bool = False) -> RefactorResult:
        errors = validate_plan(plan, self.workspace.root)
        if not plan.complete or any(d.severity == "error" for d in plan.diagnostics) or errors:
            return RefactorResult(
                session_id=plan.session_id,
                success=False,
                changes=[],
                tests_passed=False,
                error="Plan is incomplete or failed preflight"
                + (f": {errors[0].message}: {errors[0].file}" if errors else ""),
            )
        # A whole-file rewrite (non-empty original) must not silently drop a def/class —
        # guards against LLM rewrites (or future bugs) deleting code. Advisory modules
        # (original="") are exempt.
        for c in plan.changes:
            if c.original.strip() and c.path.endswith(".py"):
                lost = _def_names(c.original) - _def_names(c.modified)
                if lost:
                    return RefactorResult(
                        session_id=plan.session_id,
                        success=False,
                        changes=[],
                        tests_passed=False,
                        error=f"refusing change to {c.path}: would drop {', '.join(sorted(lost))}",
                    )
        from reducio.analysis import analyze_files
        from reducio.recovery import safe_target

        paths = sorted({change.path for change in plan.changes})
        before = attempted = None

        def measure():
            files = []
            for relative in paths:
                path = safe_target(self.workspace.root, relative)
                if path.exists():
                    files.append(FileInfo(path=relative, content=path.read_bytes().decode("utf-8")))
            return analyze_files(files, self.cfg, scope="affected files")

        def validate_after():
            nonlocal attempted
            attempted = measure()
            if not attempted.complete:
                raise ValueError("Post-apply measurements are incomplete")

        try:
            before = measure()
            if not before.complete:
                raise ValueError("Pre-apply measurements are incomplete")
        except Exception:
            return RefactorResult(
                session_id=plan.session_id,
                success=False,
                changes=[],
                tests_passed=False,
                error="Cannot measure affected files safely",
                measurements_before=before,
            )

        pairs = [(c.path, _change_to_diff(c)) for c in plan.changes]
        result = self.workspace.apply_changes_safe(
            pairs, run_tests=run_tests, validate_after=validate_after
        )
        if result["success"]:
            after = attempted if attempted is not None else before
        else:
            try:
                after = measure()
            except Exception:
                after = None
        return RefactorResult(
            session_id=plan.session_id,
            success=result["success"],
            changes=plan.changes if result["success"] else [],
            tests_passed=result["tests_passed"],
            error=result.get("error"),
            metrics_before=_totals(before),
            metrics_after=_totals(after),
            measurements_before=before,
            measurements_after=after,
            measurements_attempted=attempted,
            **{
                key: result[key]
                for key in (
                    "test_status",
                    "test_output",
                    "test_command",
                    "test_count",
                    "recovery_status",
                    "recovery_errors",
                    "backup_location",
                )
                if key in result
            },
        )


def _totals(measurement: AnalyzeResult | None) -> ComplexityMetrics | None:
    if measurement is None or not measurement.complete:
        return None
    return ComplexityMetrics(
        lines_of_code=sum(measurement.file_lines.values()),
        cyclomatic_complexity=sum(f.cyclomatic_complexity for f in measurement.functions),
        cognitive_complexity=sum(f.cognitive_complexity for f in measurement.functions),
    )


def _def_names(src: str) -> set[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    return {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }


def _change_to_diff(change) -> str:
    if not change.original and change.modified:
        lines = change.modified.splitlines()
        body = "\n".join(f"+{ln}" for ln in lines)
        return f"--- /dev/null\n+++ b/{change.path}\n@@ -0,0 +1,{len(lines)} @@\n{body}"
    # Split on "\n" (not splitlines) so difflib's 1-based line numbers line up
    # exactly with diff.apply_unified_diff's split("\n") — context validation then
    # passes when disk == original and fails loudly on real drift.
    diff = list(
        difflib.unified_diff(
            change.original.split("\n"),
            change.modified.split("\n"),
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
            lineterm="",
        )
    )
    return "\n".join(diff)
