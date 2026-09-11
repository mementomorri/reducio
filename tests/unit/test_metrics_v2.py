"""Exact metric contracts: measurements must reflect syntax, not text layout."""

import pytest

from reducio.agents.quality_checker import QualityCheckerAgent
from reducio.analysis import analyze_files
from reducio.metrics import get_complexity, line_decisions, measure_functions
from reducio.models import AppConfig, FileInfo
from reducio.workspace import Workspace


@pytest.mark.parametrize(
    ("body", "cc", "cognitive"),
    [
        ('return "if for or"  # while and elif', 1, 0),
        ('"""if for or"""\nreturn 1', 1, 0),
        ("if a:\n    return 1", 2, 1),
        ("if a:\n    if b:\n        if c:\n            return 1", 4, 6),
        ("if a:\n    return 1\nelif b:\n    return 2\nelse:\n    return 3", 3, 3),
        ("if a:\n    pass\nelse:\n    if b:\n        pass", 3, 4),
        ("return a and b and c", 3, 1),
        ("return a and (b and c)", 3, 1),
        ("return a and b or c", 3, 2),
        ("return 1 if a else 2", 2, 1),
        ("for x in xs:\n    pass\nelse:\n    pass", 2, 2),
        ("while a:\n    pass", 2, 1),
        ("with resource() as r:\n    assert r", 3, 0),
        ("try:\n    pass\nexcept ValueError:\n    pass\nfinally:\n    pass", 2, 1),
        ("return [x for x in xs if x]", 3, 3),
        ("return {x: y for x in xs for y in ys}", 3, 3),
        ("return (x for x in xs)", 2, 1),
        ("return {x for x in xs}", 2, 1),
        (
            "match x:\n    case 1:\n        pass\n    case 2 if ok:\n        pass\n    case _:\n        pass",
            4,
            3,
        ),
    ],
)
def test_exact_decision_counts(body, cc, cognitive):
    source = "def f():\n" + "\n".join("    " + line for line in body.splitlines()) + "\n"
    metrics = get_complexity(source)
    assert (metrics.cyclomatic_complexity, metrics.cognitive_complexity) == (cc, cognitive)


def test_tabs_and_spaces_measure_identically():
    source = "def f():\n    if a:\n        if b:\n            return 1\n"
    assert get_complexity(source) == get_complexity(source.replace("    ", "\t"))


def test_async_and_nested_functions_have_independent_scopes():
    source = """class Service:
    async def run(self):
        async with context():
            async for item in stream():
                pass
        def inner():
            if condition:
                return 1
        return inner()
"""
    functions = measure_functions(source)
    assert [
        (f.qualified_name, f.kind, f.cyclomatic_complexity, f.cognitive_complexity)
        for f in functions
    ] == [
        ("Service.run", "method", 3, 1),
        ("Service.run.inner", "function", 2, 1),
    ]
    assert get_complexity(source).cyclomatic_complexity == 5


def test_physical_lines_and_decorators():
    assert get_complexity("").lines_of_code == 0
    assert get_complexity("x = 1\n").lines_of_code == get_complexity("x = 1").lines_of_code == 1
    function = measure_functions("@deco\ndef f():\n    # note\n    return 1\n")[0]
    assert function.lines_of_code == 4
    assert function.line == 2


def test_invalid_python_has_no_fabricated_measurement():
    with pytest.raises(SyntaxError):
        get_complexity("def broken(:")
    result = analyze_files([FileInfo(path="broken.py", content="def broken(:")], AppConfig())
    assert not result.complete
    assert not result.functions
    assert result.diagnostics[0].line == 1


def test_actual_hotspots_not_top_twenty_or_classes():
    code = "\n".join(f"def f{i}():\n    if a:\n        return 1" for i in range(25))
    cfg = AppConfig(complexity_thresholds={"cyclomatic_complexity": 2})
    result = analyze_files([FileInfo(path="many.py", content=code)], cfg)
    assert result.total_hotspots == len(result.functions) == 25
    assert result.metrics_version == 2
    assert result.model_dump()["total_hotspots"] == 25


async def test_analyze_and_check_agree(tmp_path):
    cfg = AppConfig(complexity_thresholds={"cyclomatic_complexity": 2})
    files = [
        FileInfo(
            path="source.py",
            content="class C:\n    def f(self):\n        if x:\n            return 1\n",
        )
    ]
    analysis = analyze_files(files, cfg)
    quality = await QualityCheckerAgent(Workspace(str(tmp_path), cfg)).check_quality(files, ".")
    issue = next(i for i in quality.issues if i.issue_type == "high_complexity_function")
    assert issue.symbol == analysis.hotspots[0].symbol == "C.f"
    assert "complexity 2 " in issue.message
    assert len(analysis.hotspots) == 1


def test_line_counts_ignore_text_and_do_not_double_count_nested_functions():
    assert not line_decisions('x = "if for or" # and while\n')
    assert line_decisions("def outer():\n    def inner():\n        if x:\n            pass\n") == {
        3: 1
    }
