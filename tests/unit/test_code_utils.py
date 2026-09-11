"""Tests for code_utils helpers."""

from reducio.utils.code_utils import find_python_block_end


def test_find_python_block_end_uses_indent():
    lines = ["def foo():", "    a = 1", "    b = 2", "def bar():"]
    assert find_python_block_end(lines, 0) == 3
