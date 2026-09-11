"""Unit tests for LLMRouter model selection (the tier/local/remote routing gotcha)."""

import reducio.llm.router as router_mod
from reducio.llm.router import LLMRouter
from reducio.models import ModelTier


def test_model_override_bypasses_tier():
    r = LLMRouter(model_override="ollama/custom")
    assert r.get_model_for_tier(ModelTier.HEAVY) == "ollama/custom"


def test_prefers_local_when_available(monkeypatch):
    r = LLMRouter(prefer_local=True)
    monkeypatch.setattr(r, "is_local_available", lambda: True)
    assert r.get_model_for_tier(ModelTier.MEDIUM) == "ollama/qwen2.5-coder:1.5b"


def test_falls_back_to_remote_when_local_unavailable(monkeypatch):
    r = LLMRouter(prefer_local=True)
    monkeypatch.setattr(r, "is_local_available", lambda: False)
    assert r.get_model_for_tier(ModelTier.MEDIUM) == "anthropic/claude-3-haiku-20240307"


def test_prefer_remote_ignores_local(monkeypatch):
    r = LLMRouter(prefer_local=False)
    monkeypatch.setattr(r, "is_local_available", lambda: True)
    assert r.get_model_for_tier(ModelTier.LIGHT) == "openai/gpt-4o-mini"


def test_is_local_available_caches_one_http_call(monkeypatch):
    calls = {"n": 0}

    class _Resp:
        status_code = 200

    def fake_get(url, timeout):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(router_mod.httpx, "get", fake_get)
    r = LLMRouter()
    assert r.is_local_available() is True
    assert r.is_local_available() is True  # cached — no second call
    assert calls["n"] == 1


def test_is_local_available_handles_connection_error(monkeypatch):
    def boom(url, timeout):
        raise OSError("no ollama")

    monkeypatch.setattr(router_mod.httpx, "get", boom)
    assert LLMRouter().is_local_available() is False
