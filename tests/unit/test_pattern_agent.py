"""Characterization tests for PatternAgent."""

from pathlib import Path

import pytest

from reducio.agents.pattern import PatternAgent
from reducio.models import AppConfig, FileInfo, PatternRequest
from reducio.workspace import Workspace


class _FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.called = False

    def complete(self, prompt, system_prompt=None, **kw):
        self.called = True
        return self.reply


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "test-python-code"
    / "python"
    / "patterns"
    / "complex_conditionals.py"
)


def test_strategy_pattern_on_complex_conditionals(tmp_path):
    content = FIXTURE.read_text(encoding="utf-8")
    agent = PatternAgent(Workspace(str(tmp_path)))
    plan = agent.apply_pattern(
        PatternRequest(
            pattern="strategy",
            path=str(FIXTURE.parent),
            files=[FileInfo(path=str(FIXTURE.name), content=content)],
        )
    )
    assert plan.session_id
    assert len(plan.changes) >= 1
    assert any("strategies/" in c.path for c in plan.changes)


def _apply(tmp_path, pattern: str, content: str):
    return PatternAgent(Workspace(str(tmp_path))).apply_pattern(
        PatternRequest(pattern=pattern, path=".", files=[FileInfo(path="m.py", content=content)])
    )


def test_factory_pattern_on_conditional_instantiation(tmp_path):
    content = (
        "def make(k):\n    if k == 'a':\n        return FooHandler()\n    return BarHandler()\n"
    )
    plan = _apply(tmp_path, "factory", content)
    assert any("factories/" in c.path for c in plan.changes)


def test_singleton_pattern_writes_advisory_module_not_source(tmp_path):
    # Must NOT overwrite the source file (that discarded the original code); write an
    # advisory module with original="" like every other pattern.
    content = "count = 0\n\ndef bump():\n    global count\n    count += 1\n"
    plan = _apply(tmp_path, "singleton", content)
    assert plan.changes
    assert all(c.path != "m.py" for c in plan.changes)
    assert any("singletons/" in c.path for c in plan.changes)
    assert all(c.original == "" for c in plan.changes)
    assert "class Singleton" in plan.changes[0].modified


def test_observer_pattern_on_event_keywords(tmp_path):
    plan = _apply(tmp_path, "observer", "def notify(self):\n    self.subscribe()\n")
    assert any("observers/" in c.path for c in plan.changes)


def test_unknown_pattern_returns_no_changes(tmp_path):
    with pytest.raises(ValueError, match="Unknown"):
        _apply(tmp_path, "banana", "x = 1\n")


def test_autodetect_writes_advisory_files_not_source(tmp_path):
    # Empty pattern → auto-detect. Suggestions go to NEW advisory modules, never
    # original="" against the source file (which would prepend a template into it).
    content = FIXTURE.read_text(encoding="utf-8")
    plan = PatternAgent(Workspace(str(tmp_path))).apply_pattern(
        PatternRequest(
            pattern="",
            path=str(FIXTURE.parent),
            files=[FileInfo(path="complex_conditionals.py", content=content)],
        )
    )
    assert plan.changes
    assert all(c.path != "complex_conditionals.py" for c in plan.changes)
    assert any(c.path.startswith("strategies/") for c in plan.changes)
    assert all(c.original == "" for c in plan.changes)


def test_pattern_llm_refactor_when_model_set(tmp_path):
    cfg = AppConfig()
    cfg.model = "test/model"
    content = FIXTURE.read_text(encoding="utf-8")  # triggers the strategy detector
    llm = _FakeLLM("```python\n# refactored\nclass S:\n    pass\n```")
    agent = PatternAgent(Workspace(str(tmp_path), cfg), llm)
    plan = agent.apply_pattern(
        PatternRequest(
            pattern="strategy", path=str(tmp_path), files=[FileInfo(path="c.py", content=content)]
        )
    )
    assert llm.called
    assert any(
        c.description == "LLM strategy refactor" and "refactored" in c.modified
        for c in plan.changes
    )


def test_template_class_names_are_pascal_case():
    from reducio.agents.pattern import _generate_factory_template, _generate_strategy_template

    assert "class AuthValidatorStrategy(ABC):" in _generate_strategy_template("auth_validator.py")
    assert "class AuthValidatorFactory:" in _generate_factory_template("auth_validator.py")
