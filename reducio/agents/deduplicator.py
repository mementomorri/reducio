"""Deduplicator agent — structural clone detection by AST fingerprint."""

from __future__ import annotations

import ast
import builtins
import math
import re
import symtable
from collections import defaultdict
from pathlib import Path

from reducio.agents.base import BaseAgent
from reducio.analysis import analyze_files, totals
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

    def find_duplicates(self, request: DeduplicateRequest, rewrite: bool = False) -> RefactorPlan:
        self._begin_plan()
        files = request.files or self.workspace.list_files()
        groups: dict[str, list[Block]] = defaultdict(list)
        for block in self._extract_blocks(files):
            if key := _fingerprint(block[2]):
                groups[key].append(block)
        duplicates = [group for group in groups.values() if len(group) > 1]
        if rewrite:
            return self._rewrite_exact(duplicates, files)
        self.provenance.append(
            PlanningProvenance(
                file="",
                engine="heuristic",
                outcome=(
                    "failed" if any(d.severity == "error" for d in self.diagnostics) else "scanned"
                ),
            )
        )
        near = _near_misses({key: group[0] for key, group in groups.items() if len(group) == 1})
        changes = [_dedup_change(group) for group in duplicates]
        changes += [
            _dedup_change(group, f"near-miss, {math.floor(ratio * 100)}% similar")
            for group, ratio in near
        ]
        return self._finalize_plan(
            changes,
            f"Found {len(duplicates)} duplicate group(s) and {len(near)} near-miss group(s); "
            f"proposing {len(changes)} shared-util suggestion(s) "
            "(review before adopting — call sites are not rewritten).",
            "deduplicate",
        )

    def _rewrite_exact(self, duplicates: list[list[Block]], files: list[FileInfo]) -> RefactorPlan:
        by_path = {f.path: f for f in files}
        trees = []
        for f in files:
            try:
                trees.append(f.tree)
            except SyntaxError, ValueError:
                pass  # already an error diagnostic: the plan is incomplete
        edits: dict[str, list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]] = defaultdict(
            list
        )
        created: list[FileChange] = []
        for group in duplicates:
            exact: dict[tuple[str, str, str], list[Block]] = defaultdict(list)
            for block in group:
                exact[(Path(block[0]).parent.as_posix(), block[1].name, ast.dump(block[1]))].append(
                    block
                )
            if len(exact) == len(group):
                self.diagnostics.append(
                    PlanDiagnostic(
                        code="structural_clone",
                        file=group[0][0],
                        severity="info",
                        message=f"'{group[0][1].name}' has structural clones that differ in "
                        "names or literals; run without --rewrite for a suggestion.",
                    )
                )
            for (directory, name, _), copies in exact.items():
                if len(copies) < 2:
                    continue
                shared = (Path(directory) / f"_{name}_shared.py").as_posix()
                refusal = self._group_refusal(directory, name, shared, copies, by_path, trees)
                if refusal:
                    self.diagnostics.append(
                        PlanDiagnostic(
                            code="unsafe_duplicate",
                            file=copies[0][0],
                            message=f"Not rewriting '{name}' ({len(copies)} copies): {refusal}.",
                        )
                    )
                    continue
                futures = _futures(by_path[copies[0][0]].tree)
                header = f"from __future__ import {', '.join(futures)}\n" if futures else ""
                created.append(
                    FileChange(
                        path=shared,
                        original="",
                        modified=f"# Shared by `reducio deduplicate --rewrite`: "
                        f"{', '.join(p for p, _, _ in copies)}\n{header}{copies[0][2]}\n",
                        description=f"Single shared definition of '{name}' ({len(copies)} identical copies)",
                        operation="create",
                    )
                )
                for path, node, _ in copies:
                    edits[path].append((node, f"from ._{name}_shared import {name}"))
        changes = list(created)
        for path, spans in sorted(edits.items()):
            content = by_path[path].content
            for node, text in sorted(spans, key=lambda span: -span[0].lineno):
                content = _replace_span(content, node, text) or content
            changes.append(
                FileChange(
                    path=path,
                    original=by_path[path].content,
                    modified=content,
                    description=f"Import {len(spans)} shared definition(s) instead of local copies",
                    operation="replace",
                    encoding=by_path[path].encoding,
                )
            )
        self.provenance.append(
            PlanningProvenance(
                file="", engine="heuristic", outcome="proposed" if changes else "scanned"
            )
        )
        before = totals(
            analyze_files([by_path[p] for p in edits], self.workspace.cfg, announce=False)
        )
        after = totals(
            analyze_files(
                [FileInfo(path=c.path, content=c.modified) for c in changes],
                self.workspace.cfg,
                announce=False,
            )
        )
        predicted = (
            f"; predicted physical lines {before.lines_of_code} → {after.lines_of_code}, "
            f"total CC {before.cyclomatic_complexity} → {after.cyclomatic_complexity}"
            if before and after and changes
            else ""
        )
        return self._finalize_plan(
            changes,
            f"Rewrote {len(created)} exact duplicate group(s) into shared sibling modules"
            f"{predicted} (callers keep working through the same module names; review before applying).",
            "deduplicate",
        )

    def _group_refusal(
        self,
        directory: str,
        name: str,
        shared: str,
        copies: list[Block],
        by_path: dict[str, FileInfo],
        trees: list[ast.Module],
    ) -> str | None:
        root = self.workspace.root / directory
        if len({path for path, _, _ in copies}) != len(copies):
            return "copies share one file"
        if not (root / "__init__.py").is_file():
            return (
                f"{directory} is not a package (no __init__.py), so a relative import cannot work"
            )
        if shared in by_path or (self.workspace.root / shared).exists():
            return f"{shared} already exists"
        init = (root / "__init__.py").read_text(errors="replace")
        if re.search(rf"\b_{re.escape(name)}_shared\b", init):
            return f"__init__.py already uses the name _{name}_shared"
        if len({tuple(_futures(by_path[path].tree)) for path, _, _ in copies}) != 1:
            return "copies differ in __future__ imports"
        for path, node, _ in copies:
            module = by_path[path]
            reason = _module_refusal(module.tree, module.content, name) or _function_refusal(node)
            if reason is None and _replace_span(module.content, node, "") is None:
                reason = "definition shares a line with other code"
            if reason:
                return f"{path}: {reason}"
        if _escapes(name, trees):
            return f"'{name}' is used other than as a direct call (identity could be observed)"
        return None

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
            } | _global_rebindings(module_scope)
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
    # Exact structural clones of 2+ statements; near misses compare these keys (_near_misses).
    return ast.dump(node) if len(node.body) > 1 else None


NEAR_MISS = 0.9


def _near_misses(singles: dict[str, Block]) -> list[tuple[list[Block], float]]:
    """Group leftover functions whose normalized ASTs are >= NEAR_MISS similar (suggest-only)."""
    from difflib import SequenceMatcher

    items = sorted(
        (
            (sum(isinstance(n, ast.stmt) for n in ast.walk(b[1])), re.findall(r"\w+|[^\w\s]", k), b)
            for k, b in singles.items()
        ),
        key=lambda item: (item[0], item[2][0], item[2][1].lineno),
    )
    used: set[int] = set()
    groups = []
    # ponytail: O(n²) within ±1 statement-count buckets; MinHash/LSH if large repos get slow.
    for i, (size, tokens, block) in enumerate(items):
        if i in used:
            continue
        matcher, members, ratios = SequenceMatcher(None, autojunk=False), [block], []
        matcher.set_seq2(tokens)
        for j in range(i + 1, len(items)):
            other_size, other, candidate = items[j]
            if other_size > size + 1:
                break
            if j in used:
                continue
            matcher.set_seq1(other)
            if matcher.real_quick_ratio() >= NEAR_MISS and matcher.quick_ratio() >= NEAR_MISS:
                if (ratio := matcher.ratio()) >= NEAR_MISS:
                    used.add(j)
                    members.append(candidate)
                    ratios.append(ratio)
        if ratios:
            groups.append((members, min(ratios)))
    return groups


def _dedup_change(group: list[Block], kind: str = "") -> FileChange:
    path, node, content = group[0]
    return FileChange(
        path=advisory_path("utils", path, f"{node.name}_{node.lineno}_dedup"),
        original="",
        modified=content,
        description=(
            f"Proposed shared util for '{node.name}' from {len(group)} sites "
            + (f"({kind}: copies differ; reconcile before adopting) " if kind else "")
            + "(suggestion only; applying writes the utility module; "
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
    # Recursion is self-contained; builtins need no accompanying import. Dunders such as
    # __name__/__spec__ resolve in the module's globals first, so they never move safely.
    dynamic = {"globals", "locals", "eval", "exec", "vars"}
    allowed_builtins = (
        {n for n in dir(builtins) if not n.startswith("__")} - module_bindings - dynamic
    )
    return required - allowed_builtins - {name}


def _global_rebindings(module_scope: symtable.SymbolTable) -> set[str]:
    """Names a function rebinds via `global` (e.g. `global len; len = f`)."""
    names: set[str] = set()
    pending = list(module_scope.get_children())
    while pending:
        scope = pending.pop()
        names.update(
            s.get_name() for s in scope.get_symbols() if s.is_declared_global() and s.is_assigned()
        )
        pending.extend(scope.get_children())
    return names


# --- Exact-copy rewrite (`deduplicate --rewrite`) ------------------------------------------
#
# Same-name functions with identical source ASTs in one package directory are moved to a new,
# inert sibling module `_<name>_shared.py` and each copy becomes `from ._<name>_shared import
# <name>`. The module-level name stays bound, so callers and importers need no rewriting.
# Every precondition below refuses a case where sharing one function object could change
# behavior; refusals are reported, never guessed around.

_DYNAMIC = {"exec", "eval", "globals", "locals", "vars", "__import__"}


def _module_refusal(tree: ast.Module, content: str, name: str) -> str | None:
    if content.startswith("#!"):
        return "module has a shebang (likely run as a script)"
    bindings = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            return "module uses a star import"
        if isinstance(node, ast.Name) and node.id in _DYNAMIC:
            return f"module uses {node.id}()"
        if isinstance(node, ast.Global) and name in node.names:
            return f"'{name}' is declared global elsewhere"
        if (
            isinstance(node, ast.Name)
            and node.id == name
            and isinstance(node.ctx, ast.Store | ast.Del)
        ):
            return f"'{name}' is rebound in its module"
        if isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name:
            return f"'{name}' is also imported in its module"
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == name
        ):
            bindings += 1
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ):
            return "module has a __main__ guard (relative imports fail when run as a script)"
    return f"'{name}' is defined more than once in its module" if bindings > 1 else None


def _function_refusal(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    defaults = [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]
    if not all(isinstance(d, ast.Constant) for d in defaults):
        return "non-constant default (one shared object would share its state)"
    every = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    every += [a for a in (node.args.vararg, node.args.kwarg) if a]
    annotations = [a.annotation for a in every] + [node.returns]
    for annotation in filter(None, annotations):
        if any(
            isinstance(n, ast.Constant) and isinstance(n.value, str) for n in ast.walk(annotation)
        ):
            return "string annotation (resolved in the defining module)"
    if any(isinstance(n, ast.Name) and n.id == node.name for n in ast.walk(node)):
        return "function refers to its own name"
    return None


def _futures(tree: ast.Module) -> list[str]:
    return sorted(
        alias.name
        for stmt in tree.body
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"
        for alias in stmt.names
    )


def _escapes(name: str, trees: list[ast.Module]) -> bool:
    """True if any load of `name` is not a direct call (identity could be observed)."""
    for tree in trees:
        called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for n in ast.walk(tree):
            used = (isinstance(n, ast.Name) and n.id == name) or (
                isinstance(n, ast.Attribute) and n.attr == name
            )
            if used and isinstance(getattr(n, "ctx", None), ast.Load) and id(n) not in called:
                return True
    return False


def _replace_span(content: str, node: ast.stmt, text: str) -> str | None:
    lines = content.splitlines(keepends=True)
    first, last = node.lineno - 1, (node.end_lineno or node.lineno) - 1
    tail = lines[last].encode()[node.end_col_offset or 0 :].decode().strip()
    if node.col_offset or (tail and not tail.startswith("#")):
        return None  # shares a line with other code; no byte-exact span
    ending = lines[last][len(lines[last].rstrip("\r\n")) :] or "\n"
    return "".join([*lines[:first], text + ending, *lines[last + 1 :]])
