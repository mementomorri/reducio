"""Explicit API contracts, without network calls or real credentials."""

import asyncio
import builtins
import json

import httpx
import pytest

from reducio.llm import LLMClient, LLMError
from reducio.models import AppConfig


async def test_response_cannot_persist_token(api):
    install, _ = api
    install({"choices": [{"finish_reason": "stop", "message": {"content": "TEST_SECRET"}}]})
    with pytest.raises(LLMError, match="credentials"):
        await LLMClient(AppConfig(llm_api="openai", model="chosen")).complete("source")


async def test_total_deadline(monkeypatch):
    monkeypatch.setenv("REDUCIO_API_KEY", "TEST_SECRET")

    async def slow(*a, **kw):
        await asyncio.sleep(1)

    monkeypatch.setattr(httpx.AsyncClient, "post", slow)
    with pytest.raises(LLMError, match="timed out"):
        await LLMClient(
            AppConfig(llm_api="openai", model="chosen", llm_timeout_seconds=0.01)
        ).complete("source")


@pytest.mark.parametrize("fallback", [False, True])
async def test_app_api_failure_persists_safe_diagnostics(api, tmp_path, fallback):
    from reducio.services import App

    install, _ = api
    install({"error": "TEST_SECRET PRIVATE"}, status=401)
    (tmp_path / "sample.py").write_text("def f():\n    x = None\n    return x == None\n")
    service = App(str(tmp_path), AppConfig(llm_api="openai", model="chosen"))
    assert service.llm is None
    plan = await service.idiomatize(str(tmp_path), allow_fallback=fallback)
    assert plan.complete is fallback
    assert "HTTP 401" in plan.model_dump_json()
    saved = service.sessions.load_plan(plan.session_id)
    assert saved is not None
    assert "TEST_SECRET" not in saved.model_dump_json()
    assert "PRIVATE" not in saved.model_dump_json()


async def test_app_successful_api_plan_replays_offline(api, tmp_path, monkeypatch):
    from reducio.services import App

    install, requests = api
    install(
        {"choices": [{"finish_reason": "stop", "message": {"content": "def f():\n    return 2\n"}}]}
    )
    (tmp_path / "sample.py").write_text("def f():\n    return 1\n")
    service = App(str(tmp_path), AppConfig(llm_api="openai", model="chosen"))
    plan = await service.idiomatize(str(tmp_path))
    assert plan.complete and plan.changes
    assert len(requests) == 1
    monkeypatch.delenv("REDUCIO_API_KEY")
    replay = App(str(tmp_path), AppConfig())
    saved = replay.sessions.load_plan(plan.session_id)
    result = replay.apply_plan(saved)
    assert result.success and replay.llm is None
    assert len(requests) == 1


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("REDUCIO_API_KEY", "TEST_SECRET")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    real = httpx.AsyncClient
    requests = []

    def install(reply, status=200):
        def handler(request):
            requests.append(request)
            if isinstance(reply, Exception):
                raise reply
            return httpx.Response(status, json=reply)

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install, requests


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
async def test_protocol_headers_and_body(api, protocol):
    install, requests = api
    reply = (
        {"choices": [{"finish_reason": "stop", "message": {"content": "x = 1"}}]}
        if protocol == "openai"
        else {"stop_reason": "end_turn", "content": [{"type": "text", "text": "x = 1"}]}
    )
    install(reply)
    cfg = AppConfig(
        llm_api=protocol, model="chosen", llm_base_url="https://compatible.example/custom/v1/"
    )
    assert await LLMClient(cfg).complete("PRIVATE", system_prompt="SYSTEM") == "x = 1"
    request = requests[0]
    body = json.loads(request.content)
    assert body["model"] == "chosen" and body["stream"] is False
    assert len(requests) == 1
    if protocol == "openai":
        assert request.url.path == "/custom/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer TEST_SECRET"
        assert body["messages"][0] == {"role": "system", "content": "SYSTEM"}
        assert body["max_completion_tokens"] == 2048
    else:
        assert request.url.path == "/custom/v1/messages"
        assert request.headers["x-api-key"] == "TEST_SECRET"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert body["system"] == "SYSTEM" and body["max_tokens"] == 2048
        assert body["messages"][0]["role"] == "user"


@pytest.mark.parametrize(
    "protocol,reply",
    [
        ("openai", {}),
        ("openai", {"choices": []}),
        ("openai", {"choices": [{"finish_reason": "length", "message": {"content": "x=1"}}]}),
        ("openai", {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}),
        (
            "openai",
            {"choices": [{"finish_reason": "stop", "message": {"content": "x", "refusal": "no"}}]},
        ),
        ("anthropic", {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "x=1"}]}),
        ("anthropic", {"stop_reason": "end_turn", "content": []}),
        ("anthropic", {"stop_reason": "end_turn", "content": [{"type": "tool_use"}]}),
        ("anthropic", {"stop_reason": "end_turn", "content": "wrong"}),
    ],
)
async def test_bad_responses_fail_without_fallback(api, protocol, reply):
    install, requests = api
    install(reply)
    with pytest.raises(LLMError):
        await LLMClient(AppConfig(llm_api=protocol, model="chosen")).complete("source")
    assert len(requests) == 1


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_http_errors_are_sanitized(api, status, caplog):
    install, requests = api
    install({"error": "TEST_SECRET PRIVATE"}, status)
    with pytest.raises(LLMError, match=str(status)) as error:
        await LLMClient(AppConfig(llm_api="openai", model="chosen")).complete("PRIVATE")
    assert "TEST_SECRET" not in str(error.value) + caplog.text
    assert "PRIVATE" not in str(error.value) + caplog.text
    assert len(requests) == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout("SECRET"), OSError("SECRET")])
async def test_transport_error_redaction(api, error):
    install, _ = api
    install(error)
    with pytest.raises(LLMError) as caught:
        await LLMClient(AppConfig(llm_api="openai", model="chosen")).complete("source")
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://external.example/v1",
        "https://user:secret@example.org/v1",
        "https://example.org/v1?token=secret",
        "bad",
        "https://example.org:bad/v1",
    ],
)
async def test_unsafe_endpoint_rejected_without_requests(api, url):
    _, requests = api
    with pytest.raises(LLMError, match="HTTPS"):
        await LLMClient(AppConfig(llm_api="openai", model="chosen", llm_base_url=url)).complete(
            "source"
        )
    assert not requests


@pytest.mark.parametrize("settings", [{}, {"model": "chosen"}, {"llm_api": "openai"}])
async def test_model_and_protocol_required(api, settings):
    with pytest.raises(LLMError, match="explicit model"):
        await LLMClient(AppConfig(**settings)).complete("source")


async def test_missing_key_and_standard_key_fallback(api, monkeypatch):
    install, requests = api
    monkeypatch.delenv("REDUCIO_API_KEY")
    client = LLMClient(AppConfig(llm_api="openai", model="chosen"))
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        await client.complete("source")
    monkeypatch.setenv("OPENAI_API_KEY", "STANDARD")
    install({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})
    assert await client.complete("source") == "ok"
    assert requests[0].headers["authorization"] == "Bearer STANDARD"


async def test_missing_extra_has_actionable_error(api, monkeypatch):
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "httpx":
            raise ImportError()
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(LLMError, match=r"reducio\[llm\]"):
        await LLMClient(AppConfig(llm_api="openai", model="chosen")).complete("source")
