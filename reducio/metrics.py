"""Version 2 metrics. Rules and scope boundaries are documented in docs/METRICS.md."""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable
from textwrap import dedent

from reducio.models import ComplexityMetrics, FunctionMetrics


class _Counter(ast.NodeVisitor):
    def __init__(self) -> None:
        self.cyclomatic = 1
        self.cognitive = 0
        self.depth = 0
        self.decisions: Counter[int] = Counter()

    def decision(self, node: ast.AST, count: int = 1) -> None:
        self.cyclomatic += count
        self.decisions[getattr(node, "lineno", 1)] += count

    def structural(self, node: ast.AST) -> None:
        self.decision(node)
        self.cognitive += 1 + self.depth

    def body(self, nodes: Iterable[ast.AST], nested: bool = False) -> None:
        self.depth += int(nested)
        for node in nodes:
            self.visit(node)
        self.depth -= int(nested)

    def visit_FunctionDef(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> None:
        # Each named function is measured separately, with nesting reset to zero.
        pass

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        self._if(node, chained=False)

    def _if(self, node: ast.If, chained: bool) -> None:
        self.decision(node)
        self.cognitive += 1 if chained else 1 + self.depth
        self.visit(node.test)
        self.body(node.body, nested=True)
        # AST treats elif as an if in orelse. Same-column distinguishes an actual
        # elif from a nested `else: if`, including tab-indented source.
        if (
            len(node.orelse) == 1
            and isinstance(node.orelse[0], ast.If)
            and node.orelse[0].col_offset == node.col_offset
        ):
            self._if(node.orelse[0], chained=True)
        elif node.orelse:
            self.cognitive += 1
            self.body(node.orelse, nested=True)

    def visit_For(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        self.structural(node)
        if isinstance(node, ast.While):
            self.visit(node.test)
        else:
            self.visit(node.iter)
            self.visit(node.target)
        self.body(node.body, nested=True)
        if node.orelse:
            self.cognitive += 1
            self.body(node.orelse, nested=True)

    visit_AsyncFor = visit_For
    visit_While = visit_For

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.structural(node)
        self.visit(node.test)
        self.body([node.body, node.orelse], nested=True)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.structural(node)
        if node.type:
            self.visit(node.type)
        self.body(node.body, nested=True)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        self.decision(node)  # one per with statement, regardless of context count
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Assert(self, node: ast.Assert) -> None:
        self.decision(node)
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self._boolean(node, None)

    def _boolean(self, node: ast.AST, parent_op: type | None) -> None:
        if isinstance(node, ast.BoolOp):
            self.decision(node, len(node.values) - 1)
            if type(node.op) is not parent_op:
                self.cognitive += 1
            for value in node.values:
                self._boolean(value, type(node.op))
        else:
            self.visit(node)

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        original_depth = self.depth
        for generator in node.generators:
            self.structural(generator.target)
            self.visit(generator.iter)
            self.depth += 1
            for condition in generator.ifs:
                self.structural(condition)
                self.visit(condition)
                self.depth += 1
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.depth = original_depth

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Match(self, node: ast.Match) -> None:
        self.cognitive += 1 + self.depth
        self.visit(node.subject)
        for case in node.cases:
            # Capture/default cases add no branch unless guarded.
            if not (isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None):
                self.decision(case.pattern)
            if case.guard:
                self.decision(case.guard)
                self.cognitive += 1 + self.depth + 1
                self.visit(case.guard)
            self.body(case.body, nested=True)


def _measure(nodes: Iterable[ast.AST], lines: int) -> ComplexityMetrics:
    counter = _Counter()
    counter.body(nodes)
    return ComplexityMetrics(
        cyclomatic_complexity=counter.cyclomatic,
        cognitive_complexity=counter.cognitive,
        lines_of_code=lines,
    )


def functions_from_tree(tree: ast.AST, path: str) -> list[FunctionMetrics]:
    functions: list[FunctionMetrics] = []

    def walk(node: ast.AST, parents: tuple[str, ...] = (), scope: str = "module") -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if not isinstance(node, ast.ClassDef):
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                end = node.end_lineno or node.lineno
                functions.append(
                    FunctionMetrics(
                        file=path,
                        name=node.name,
                        qualified_name=".".join((*parents, node.name)),
                        kind="method" if scope == "class" else "function",
                        line=node.lineno,
                        end_line=end,
                        **_measure(node.body, end - start + 1).model_dump(),
                    )
                )
            parents = (*parents, node.name)
            scope = "class" if isinstance(node, ast.ClassDef) else "function"
        for child in ast.iter_child_nodes(node):
            walk(child, parents, scope)

    walk(tree)
    return functions


def measure_functions(content: str, path: str = "<source>") -> list[FunctionMetrics]:
    return functions_from_tree(ast.parse(content, filename=path), path)


def get_complexity(content: str) -> ComplexityMetrics:
    """Measure a snippet, including indented methods; invalid Python raises SyntaxError.

    For multi-function input, sum independent callable scores, never class totals.
    Module-only snippets are measured as one block. File LOC is always independent.
    """
    tree = ast.parse(dedent(content))
    functions = functions_from_tree(tree, "<source>")
    lines = len(content.splitlines())
    if not functions:
        return _measure(tree.body, lines)
    return ComplexityMetrics(
        cyclomatic_complexity=sum(f.cyclomatic_complexity for f in functions),
        cognitive_complexity=sum(f.cognitive_complexity for f in functions),
        lines_of_code=lines,
    )


def line_decisions(content: str) -> Counter[int]:
    """Count actual AST decisions per line for the quality checker's info rule."""
    tree = ast.parse(content)
    result: Counter[int] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            counter = _Counter()
            counter.body(node.body)
            result.update(counter.decisions)
    return result
