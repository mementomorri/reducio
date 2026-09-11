"""Deduplicator agent — semantic duplicate detection."""

from __future__ import annotations

import ast
import builtins
import symtable
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
    PlanDiagnostic,
    PlanningProvenance,
    RefactorPlan,
)
from reducto.parse import ParserError, get_complexity
from reducto.plan_review import advisory_path
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
        self._begin_plan()
        files = request.files or self.workspace.list_files()
        if not self.embedding_service.is_using_real_embeddings:
            self.diagnostics.append(
                PlanDiagnostic(
                    code="embeddings_unavailable",
                    severity="error",
                    message="Semantic embeddings unavailable; install reducto-code[embeddings] and retry.",
                )
            )
            return self._finalize_plan(
                [],
                "Semantic embeddings unavailable; no duplicates analyzed. See installation docs for the embeddings extra.",
                "deduplicate",
            )
        blocks = self._extract_blocks(files)
        try:
            groups = await self.embedding_service.find_duplicates(
                blocks, request.similarity_threshold
            )
        except Exception:
            self.diagnostics.append(
                PlanDiagnostic(
                    code="embeddings_failed",
                    severity="error",
                    message="Semantic duplicate search failed; no application permitted.",
                )
            )
            groups = []
        self.provenance.append(
            PlanningProvenance(
                file="",
                engine="embeddings",
                outcome=(
                    "failed" if any(d.severity == "error" for d in self.diagnostics) else "scanned"
                ),
            )
        )
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
            try:
                self.workspace.get_symbols(f.path, f.content)
                tree = ast.parse(f.content)
                module_scope = symtable.symtable(f.content, f.path, "exec")
            except ParserError, SyntaxError, ValueError:
                self.diagnostics.append(
                    PlanDiagnostic(
                        code="parser_failed",
                        file=f.path,
                        severity="error",
                        message="Python parsing failed; duplicate analysis is incomplete.",
                    )
                )
                continue
            top = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node not in top:
                    self.diagnostics.append(
                        PlanDiagnostic(
                            code="unsupported_scope",
                            file=f.path,
                            message=f"Skipped {node.name}: methods and nested functions are not standalone utilities.",
                        )
                    )
            for node in top:
                content = ast.get_source_segment(f.content, node) or ""
                bindings = {
                    s.get_name()
                    for s in module_scope.get_symbols()
                    if s.is_assigned() or s.is_imported()
                }
                dependencies = _dependencies(content, node.name, bindings)
                if node.decorator_list or dependencies:
                    self.diagnostics.append(
                        PlanDiagnostic(
                            code="dependencies",
                            file=f.path,
                            message=f"Skipped {node.name}: decorators or external dependencies require review.",
                        )
                    )
                    continue
                try:
                    metrics = get_complexity(content)
                except SyntaxError, ValueError:
                    continue  # invalid snippets have no trustworthy numeric score
                blocks.append(
                    CodeBlock(
                        id=f"{f.path}:{node.lineno}:{node.name}",
                        file=f.path,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        content=content,
                        language=lang,
                        symbol_type="function",
                        symbol_name=node.name,
                        metrics=metrics,
                    )
                )
        return blocks

    def _create_dedup_change(self, group: list[CodeBlock]) -> FileChange | None:
        primary = group[0]
        return FileChange(
            path=advisory_path(
                "utils", primary.file, f"{primary.symbol_name}_{primary.start_line}_dedup"
            ),
            original="",
            modified=primary.content,
            description=(
                f"Proposed shared util for '{primary.symbol_name}' from {len(group)} sites "
                "(suggestion only; applying writes the utility module; "
                "originals and call sites are not rewritten)"
            ),
        )


def _dependencies(content: str, name: str, module_bindings: set[str]) -> set[str]:
    """Conservatively reject names that need the original module's namespace."""
    table = symtable.symtable(content, "<advisory>", "exec")
    required: set[str] = set()
    pending = [table]
    while pending:
        scope = pending.pop()
        required.update(
            s.get_name()
            for s in scope.get_symbols()
            if (s.is_referenced() or s.is_declared_global()) and s.is_global()
        )
        pending.extend(scope.get_children())
    # Recursion is self-contained; builtins need no accompanying import.
    dynamic = {"globals", "locals", "eval", "exec", "__import__"}
    allowed_builtins = set(dir(builtins)) - module_bindings - dynamic
    return required - allowed_builtins - {name}
