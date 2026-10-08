"""Installed-client API contracts, using only mock transports and fake credentials."""

import os

import httpx

from reducio.llm import LLMClient, LLMError
from reducio.models import AppConfig


def check() -> None:
    real_client = httpx.Client
    prior = os.environ.get("REDUCIO_API_KEY")
    os.environ["REDUCIO_API_KEY"] = "smoke-placeholder"
    try:
        for protocol in ("openai", "anthropic"):
            requests = []

            def respond(request):
                requests.append(request)
                body = (
                    {"choices": [{"finish_reason": "stop", "message": {"content": "x = 1"}}]}
                    if protocol == "openai"
                    else {"stop_reason": "end_turn", "content": [{"type": "text", "text": "x = 1"}]}
                )
                return httpx.Response(200, json=body)

            httpx.Client = lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
            # Local-only by default: a remote endpoint is refused before any request.
            try:
                LLMClient(AppConfig(llm_api=protocol, model="mock-model")).complete("x = 1")
            except LLMError as error:
                assert "--allow-remote" in str(error)
            else:
                raise AssertionError("remote endpoint used without consent")
            assert not requests
            client = LLMClient(AppConfig(llm_api=protocol, model="mock-model", allow_remote=True))
            assert client.complete("x = 1") == "x = 1"
            assert len(requests) == 1
    finally:
        httpx.Client = real_client
        if prior is None:
            os.environ.pop("REDUCIO_API_KEY", None)
        else:
            os.environ["REDUCIO_API_KEY"] = prior


if __name__ == "__main__":
    check()
    print("Optional API client verified with mocked transports")
