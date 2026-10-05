"""Unit tests for parsing."""

import ast

from reducio.parse import get_complexity, symbols_from_tree


def test_get_complexity_counts_branches():
    code = "def f():\n    if a:\n        if b:\n            return 1\n"
    m = get_complexity(code)
    assert m.cyclomatic_complexity >= 2


def test_python_symbols():
    code = "class Foo:\n    def bar(self):\n        pass\n"
    syms = symbols_from_tree(ast.parse(code), "t.py")
    names = {s.name for s in syms}
    assert "Foo" in names
    assert "bar" in names
