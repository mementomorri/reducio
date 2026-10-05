"""Deduplicator agent — structural clone detection by AST fingerprint."""

from __future__ import annotations

import ast
import builtins
import symtable
from collections import defaultdict

from reducio.agents.base import BaseAgent
from reducio.models import (
    DeduplicateRequest,
    FileChange,
    FileInfo,
    Language,
    PlanDiagnostic,
    PlanningProvenance,
    RefactorPlan,
)
from reducio.plan_review import advisory_path
from reducio.repo import detect_language
from reducio.workspace import Workspace

Block = tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, str]  # (path, node, source)


class DeduplicatorAgent(BaseAgent):
    workspace: Workspace

    def find_duplicates(self, request: DeduplicateRequest) -> RefactorPlan:
        self._begin_plan()
        groups: dict[str, list[Block]] = defaultdict(list)
        for block in self._extract_blocks(request.files or self.workspace.list_files()):
            if key := _fingerprint(block[2]):
                groups[key].append(block)
        duplicates = [group for group in groups.values() if len(group) > 1]
        self.provenance.append(
            PlanningProvenance(
                file="",
                engine="heuristic",
                outcome=(
                    "failed" if any(d.severity == "error" for d in self.diagnostics) else "scanned"
                ),
            )
        )
        changes = [_dedup_change(group) for group in duplicates]
        return self._finalize_plan(
            changes,
            f"Found {len(duplicates)} duplicate group(s); proposing {len(changes)} shared-util "
            "suggestion(s) (review before adopting — call sites are not rewritten).",
            "deduplicate",
        )

    def _extract_blocks(self, files: list[FileInfo]) -> list[Block]:
        blocks: list[Block] = []
        for f in files:
            if not f.error and detect_language(f.path) == Language.UNKNOWN:
                continue
            try:
                tree = f.tree
                module_scope = symtable.symtable(f.content, f.path, "exec")
            except SyntaxError, ValueError:
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
            bindings = {
                s.get_name()
                for s in module_scope.get_symbols()
                if s.is_assigned() or s.is_imported()
            }
            for node in top:
                content = ast.get_source_segment(f.content, node) or ""
                if node.decorator_list or _dependencies(content, node.name, bindings):
                    self.diagnostics.append(
                        PlanDiagnostic(
                            code="dependencies",
                            file=f.path,
                            message=f"Skipped {node.name}: decorators or external dependencies require review.",
                        )
                    )
                    continue
                blocks.append((f.path, node, content))
        return blocks


def _fingerprint(content: str) -> str | None:
    """Key equal for functions that differ only in identifiers, literals and docstring."""
    node = ast.parse(content).body[0]
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    if ast.get_docstring(node) is not None:
        node.body = node.body[1:]
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            n.id = "_"
        elif isinstance(n, ast.arg):
            n.arg, n.annotation = "_", None
        elif isinstance(n, ast.Constant):
            n.value = type(n.value).__name__
    node.name, node.returns = "_", None
    # ponytail: exact structural clones of 2+ statements only; near-miss clones need a fuzzy matcher.
    return ast.dump(node) if len(node.body) > 1 else None


def _dedup_change(group: list[Block]) -> FileChange:
    path, node, content = group[0]
    return FileChange(
        path=advisory_path("utils", path, f"{node.name}_{node.lineno}_dedup"),
        original="",
        modified=content,
        description=(
            f"Proposed shared util for '{node.name}' from {len(group)} sites "
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
