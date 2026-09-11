"""Regression test for ROADMAP P0: heuristic idiomatize apply must land edits at the
correct lines and never corrupt the top of the file."""

import ast

from reducio.models import AppConfig
from reducio.services import App

CONTENT = '''"""Module docstring that must survive."""

import os


def build(items):
    result = []
    for item in items:
        result.append(item * 2)
    return result


def untouched():
    return os.getcwd()
'''


async def test_idiomatize_apply_lands_at_correct_lines(tmp_path):
    src = tmp_path / "build.py"
    src.write_text(CONTENT)

    app = App(str(tmp_path), AppConfig())
    plan = await app.idiomatize(str(tmp_path))

    # One whole-file change for the one file (not one change per idiom).
    assert len(plan.changes) == 1

    result = app.apply_plan(plan, run_tests=False)
    assert result.success, result.error

    text = src.read_text()
    ast.parse(text)  # still valid Python after apply
    # Top of file untouched (the old bug overwrote line 1).
    assert text.startswith('"""Module docstring that must survive."""')
    # Edit landed where the loop was.
    assert "result = [item * 2 for item in items]" in text
    assert "result.append" not in text
    # Everything else intact.
    assert "import os" in text
    assert "def untouched" in text
    assert "return os.getcwd()" in text
