"""Idiomatizer agent smoke test."""

import ast

import pytest

from reducio.agents.idiomatizer import IdiomatizerAgent
from reducio.models import AppConfig, FileInfo, IdiomatizeRequest
from reducio.workspace import Workspace


async def _idioms(tmp_path, content: str, llm=None, model: str = ""):
    cfg = AppConfig()
    cfg.model = model
    agent = IdiomatizerAgent(Workspace(str(tmp_path), cfg), llm)
    return await agent.idiomatize(
        IdiomatizeRequest(path=str(tmp_path), files=[FileInfo(path="f.py", content=content)])
    )


class _FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.called = False

    async def complete(self, prompt, system_prompt=None, **kw):
        self.called = True
        return self.reply


@pytest.mark.asyncio
async def test_idiomatize_empty_files(tmp_path):
    ws = Workspace(str(tmp_path))
    agent = IdiomatizerAgent(ws)
    plan = await agent.idiomatize(IdiomatizeRequest(path=str(tmp_path), files=[]))
    assert plan.session_id
    assert isinstance(plan.changes, list)


@pytest.mark.asyncio
async def test_idiomatize_list_comp_from_for_append(tmp_path):
    content = (
        "def build():\n"
        "    out = []\n"
        "    for x in range(3):\n"
        "        out.append(x * 2)\n"
        "    return out\n"
    )
    ws = Workspace(str(tmp_path))
    agent = IdiomatizerAgent(ws)
    plan = await agent.idiomatize(
        IdiomatizeRequest(
            path=str(tmp_path),
            files=[{"path": "build.py", "content": content}],
        )
    )
    assert len(plan.changes) == 1
    assert "for " in plan.changes[0].original
    assert "for " in plan.changes[0].modified and " in " in plan.changes[0].modified


@pytest.mark.asyncio
async def test_idiomatize_skips_non_python(tmp_path):
    content = "var x = 1;\nfunction f() { return x; }\n"
    ws = Workspace(str(tmp_path))
    agent = IdiomatizerAgent(ws)
    plan = await agent.idiomatize(
        IdiomatizeRequest(
            path=str(tmp_path),
            files=[FileInfo(path="app.js", content=content)],
        )
    )
    assert plan.changes == []


@pytest.mark.asyncio
async def test_idiomatize_dict_comp(tmp_path):
    content = "def f(ns):\n    result = {}\n    for n in ns:\n        result[n] = n * n\n    return result\n"
    plan = await _idioms(tmp_path, content)
    assert any("dict comprehension" in c.description for c in plan.changes)
    assert any("{n: n * n for n in ns}" in c.modified for c in plan.changes)


@pytest.mark.asyncio
async def test_idiomatize_filtered_list_comp(tmp_path):
    content = "def f(ns):\n    out = []\n    for n in ns:\n        if n > 0:\n            out.append(n)\n    return out\n"
    plan = await _idioms(tmp_path, content)
    assert any("if n > 0" in c.modified and "for n in ns" in c.modified for c in plan.changes)


@pytest.mark.asyncio
async def test_idiomatize_nested_paren_append_is_valid(tmp_path):
    content = (
        "def f(a, b):\n    out = []\n    for x in a:\n        out.append((x, b))\n    return out\n"
    )
    plan = await _idioms(tmp_path, content)
    assert plan.changes
    ast.parse(plan.changes[0].modified.strip())  # nested parens preserved -> valid Python
    assert "(x, b)" in plan.changes[0].modified


@pytest.mark.asyncio
async def test_idiomatize_skips_accumulator_referencing_loop(tmp_path):
    # Order-preserving dedup: the filter reads the accumulator `u`. Rewriting to
    # `[v for v in t if v not in u]` changes behaviour (u is empty in the comp), so
    # this loop must be left alone. (Was a real correctness bug.)
    content = (
        "def s(t):\n"
        "    u = []\n"
        "    for v in t:\n"
        "        if v not in u:\n"
        "            u.append(v)\n"
        "    return u\n"
    )
    plan = await _idioms(tmp_path, content)
    assert not any("list comprehension" in c.description for c in plan.changes)
    # nothing else matches -> no change emitted for this file
    assert plan.changes == []


@pytest.mark.asyncio
async def test_idiomatize_compare_to_none(tmp_path):
    plan = await _idioms(tmp_path, "def f(x):\n    if x == None:\n        return 1\n    return 2\n")
    assert any("is None" in c.modified for c in plan.changes)


@pytest.mark.asyncio
async def test_dict_comp_skipped_for_list_index(tmp_path):
    # arr is a list (no {} init) -> must NOT be rewritten as a dict comprehension.
    content = (
        "def f(n):\n    arr = [0] * n\n    for i in range(n):\n        arr[i] = i\n    return arr\n"
    )
    plan = await _idioms(tmp_path, content)
    assert not any("dict comprehension" in c.description for c in plan.changes)


@pytest.mark.asyncio
async def test_idiomatize_llm_path_when_model_set(tmp_path):
    llm = _FakeLLM("```python\ndef f():\n    return 1\n```")
    content = "def f():\n    x = []\n    for i in range(3):\n        x.append(i)\n    return x\n"
    plan = await _idioms(tmp_path, content, llm=llm, model="test/model")
    assert llm.called
    assert any(
        c.description == "LLM idiomatic rewrite" and "return 1" in c.modified for c in plan.changes
    )


@pytest.mark.asyncio
async def test_idiomatize_skips_llm_without_model(tmp_path):
    llm = _FakeLLM("unused")
    await _idioms(tmp_path, "x = 1\n", llm=llm, model="")
    assert llm.called is False


@pytest.mark.asyncio
async def test_idiomatize_len_truthiness(tmp_path):
    plan = await _idioms(
        tmp_path, "def f(items):\n    if len(items) > 0:\n        return 1\n    return 0\n"
    )
    # Whole-file change now (see ROADMAP P0): assert the rewritten line is present.
    assert any("    if items:\n" in c.modified for c in plan.changes)


@pytest.mark.asyncio
async def test_idiomatize_len_zero_truthiness(tmp_path):
    plan = await _idioms(tmp_path, "def f(xs):\n    while len(xs) == 0:\n        return 1\n")
    assert any("while not xs:" in c.modified for c in plan.changes)


@pytest.mark.asyncio
async def test_idiomatize_or_chain_to_in(tmp_path):
    plan = await _idioms(
        tmp_path, 'def f(d):\n    if d == "Sat" or d == "Sun":\n        return 1\n    return 0\n'
    )
    assert any('d in ("Sat", "Sun")' in c.modified for c in plan.changes)


@pytest.mark.asyncio
async def test_truthiness_left_alone_outside_boolean_context(tmp_path):
    # len(x) > 0 as a returned value (not an if/while line) must not be rewritten.
    plan = await _idioms(tmp_path, "def f(x):\n    result = len(x) > 0\n    return result\n")
    assert not any("truthiness" in c.description for c in plan.changes)
