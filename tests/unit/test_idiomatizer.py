"""Idiomatizer agent: model-only rewrites."""

from reducio.agents.idiomatizer import IdiomatizerAgent
from reducio.models import AppConfig, FileInfo, IdiomatizeRequest
from reducio.workspace import Workspace


def _idioms(tmp_path, content: str, llm=None):
    cfg = AppConfig(llm_api="openai", model="chosen")
    agent = IdiomatizerAgent(Workspace(str(tmp_path), cfg), llm)
    return agent.idiomatize(
        IdiomatizeRequest(path=str(tmp_path), files=[FileInfo(path="f.py", content=content)])
    )


class _FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.called = False

    def complete(self, prompt, system_prompt=None, **kw):
        self.called = True
        return self.reply


def test_idiomatize_uses_model_rewrite(tmp_path):
    llm = _FakeLLM("```python\ndef f():\n    return 1\n```")
    plan = _idioms(tmp_path, "def f():\n    x = 1\n    return x\n", llm=llm)
    assert llm.called and plan.complete
    assert [c.description for c in plan.changes] == ["LLM idiomatic rewrite"]
    assert plan.changes[0].modified == "def f():\n    return 1\n"


def test_idiomatize_without_router_is_incomplete(tmp_path):
    plan = _idioms(tmp_path, "x = 1\n")
    assert not plan.complete and not plan.changes
    assert plan.diagnostics[0].code == "model_failed"


def test_idiomatize_skips_non_python_and_reports_invalid_source(tmp_path):
    llm = _FakeLLM("unused")
    cfg = AppConfig(llm_api="openai", model="chosen")
    plan = IdiomatizerAgent(Workspace(str(tmp_path), cfg), llm).idiomatize(
        IdiomatizeRequest(
            path=str(tmp_path),
            files=[
                FileInfo(path="notes.md", content="# x"),
                FileInfo(path="bad.py", content="def broken(:"),
            ],
        )
    )
    assert not llm.called and not plan.complete
    assert [d.code for d in plan.diagnostics] == ["invalid_source"]
