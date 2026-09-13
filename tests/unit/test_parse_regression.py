"""Regression guards for the tree-sitter `Language` shadow bug (commit efb9188)."""

from reducio.models import Language
from reducio.parse import get_symbols


def test_nested_function_is_not_a_method():
    symbols = get_symbols("class A:\n    def outer(self):\n        def inner(): pass\n", "a.py")
    assert {s.name: s.type for s in symbols} == {
        "A": "class",
        "outer": "method",
        "inner": "function",
    }


def test_get_symbols_extracts_class_and_method():
    syms = get_symbols("class Foo:\n    def bar(self):\n        pass\n", "t.py", Language.PYTHON)
    by_name = {s.name: s.type for s in syms}
    assert by_name.get("Foo") == "class"
    assert by_name.get("bar") == "method"
