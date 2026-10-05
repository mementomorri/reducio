"""Python AST symbols; the same scope traversal supplies function metrics."""

import ast

from reducio.metrics import functions_from_tree
from reducio.metrics import get_complexity as get_complexity
from reducio.models import Symbol


def symbols_from_tree(tree: ast.Module, path: str, functions=None) -> list[Symbol]:
    functions = functions if functions is not None else functions_from_tree(tree, path)
    return [
        Symbol(name=f.name, type=f.kind, file=path, start_line=f.line, end_line=f.end_line)
        for f in functions
    ] + [
        Symbol(
            name=n.name,
            type="class",
            file=path,
            start_line=n.lineno,
            end_line=n.end_lineno or n.lineno,
        )
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef)
    ]
