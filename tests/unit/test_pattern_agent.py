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

    async def complete(self, prompt, system_prompt=None, **kw):
        self.called = True
        return self.reply


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "test-python-code"
    / "python"
    / "patterns"
    / "complex_conditionals.py"
)


@pytest.mark.asyncio
async def test_strategy_pattern_on_complex_conditionals():
    content = FIXTURE.read_text(encoding="utf-8")
    agent = PatternAgent()
    plan = await agent.apply_pattern(
        PatternRequest(
            pattern="strategy",
            path=str(FIXTURE.parent),
            files=[FileInfo(path=str(FIXTURE.name), content=content)],
        )
    )
    assert plan.session_id
    assert len(plan.changes) >= 1
    assert any("strategies/" in c.path for c in plan.changes)


async def _apply(pattern: str, content: str):
    return await PatternAgent().apply_pattern(
        PatternRequest(pattern=pattern, path=".", files=[FileInfo(path="m.py", content=content)])
    )


@pytest.mark.asyncio
async def test_factory_pattern_on_conditional_instantiation():
    content = (
        "def make(k):\n    if k == 'a':\n        return FooHandler()\n    return BarHandler()\n"
    )
    plan = await _apply("factory", content)
    assert any("factories/" in c.path for c in plan.changes)


@pytest.mark.asyncio
async def test_singleton_pattern_writes_advisory_module_not_source():
    # Must NOT overwrite the source file (that discarded the original code); write an
    # advisory module with original="" like every other pattern.
    content = "count = 0\n\ndef bump():\n    global count\n    count += 1\n"
    plan = await _apply("singleton", content)
    assert plan.changes
    assert all(c.path != "m.py" for c in plan.changes)
    assert any("singletons/" in c.path for c in plan.changes)
    assert all(c.original == "" for c in plan.changes)
    assert "class Singleton" in plan.changes[0].modified


@pytest.mark.asyncio
async def test_observer_pattern_on_event_keywords():
    plan = await _apply("observer", "def notify(self):\n    self.subscribe()\n")
    assert any("observers/" in c.path for c in plan.changes)


@pytest.mark.asyncio
async def test_unknown_pattern_returns_no_changes():
    plan = await _apply("banana", "x = 1\n")
    assert plan.changes == []


@pytest.mark.asyncio
async def test_autodetect_writes_advisory_files_not_source():
    # Empty pattern → auto-detect. Suggestions go to NEW advisory modules, never
    # original="" against the source file (which would prepend a template into it).
    content = FIXTURE.read_text(encoding="utf-8")
    plan = await PatternAgent().apply_pattern(
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


@pytest.mark.asyncio
async def test_pattern_llm_refactor_when_model_set(tmp_path):
    cfg = AppConfig()
    cfg.model = "test/model"
    content = FIXTURE.read_text(encoding="utf-8")  # triggers the strategy detector
    llm = _FakeLLM("```python\n# refactored\nclass S:\n    pass\n```")
    agent = PatternAgent(Workspace(str(tmp_path), cfg), llm)
    plan = await agent.apply_pattern(
        PatternRequest(
            pattern="strategy", path=str(tmp_path), files=[FileInfo(path="c.py", content=content)]
        )
    )
    assert llm.called
    assert any(
        c.description == "LLM strategy refactor" and "refactored" in c.modified
        for c in plan.changes
    )
