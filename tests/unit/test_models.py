"""Pydantic model tests."""

from reducio.models import (
    CodeBlock,
    FileChange,
    FileInfo,
    Language,
    RefactorPlan,
    Symbol,
)


def test_file_info():
    info = FileInfo(path="test.py", content="pass", hash="abc")
    assert info.path == "test.py"
    assert info.hash == "abc"


def test_symbol_defaults():
    s = Symbol(name="f", type="function", file="t.py", start_line=1, end_line=2)
    assert s.references == []
    assert s.signature is None


def test_complexity_metrics_json(sample_complexity_metrics):
    data = sample_complexity_metrics.model_dump()
    assert data["cyclomatic_complexity"] == 5
    assert data["lines_of_code"] == 20


def test_refactor_plan():
    plan = RefactorPlan(
        session_id="s1",
        changes=[FileChange(path="a.py", original="a", modified="b", description="d")],
        description="test",
    )
    assert len(plan.changes) == 1


def test_code_block(sample_complexity_metrics):
    block = CodeBlock(
        id="b1",
        file="m.py",
        start_line=1,
        end_line=5,
        content="def x(): pass",
        language=Language.PYTHON,
        symbol_type="function",
        symbol_name="x",
        metrics=sample_complexity_metrics,
    )
    assert block.language == Language.PYTHON
