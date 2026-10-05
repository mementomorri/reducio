"""Regression guards for symbol kinds (nested functions are not methods)."""

import ast

from reducio.parse import symbols_from_tree


def test_nested_function_is_not_a_method():
    symbols = symbols_from_tree(
        ast.parse("class A:\n    def outer(self):\n        def inner(): pass\n"), "a.py"
    )
    assert {s.name: s.type for s in symbols} == {
        "A": "class",
        "outer": "method",
        "inner": "function",
    }


def test_get_symbols_extracts_class_and_method():
    syms = symbols_from_tree(ast.parse("class Foo:\n    def bar(self):\n        pass\n"), "t.py")
    by_name = {s.name: s.type for s in syms}
    assert by_name.get("Foo") == "class"
    assert by_name.get("bar") == "method"
