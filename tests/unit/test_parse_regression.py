"""Regression guards for the tree-sitter `Language` shadow bug (commit efb9188)."""

from reducio.models import Language
from reducio.parse import _parser, get_symbols


def test_parser_builds_not_shadowed():
    # If tree_sitter.Language is shadowed by the models enum again, _parser()
    # swallows the constructor error and returns None -> get_symbols() == [].
    assert _parser() is not None


def test_get_symbols_extracts_class_and_method():
    syms = get_symbols("class Foo:\n    def bar(self):\n        pass\n", "t.py", Language.PYTHON)
    by_name = {s.name: s.type for s in syms}
    assert by_name.get("Foo") == "class"
    assert by_name.get("bar") == "method"
