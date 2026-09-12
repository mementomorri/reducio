"""Installed-client API contracts, using only mock transports and fake credentials."""

import asyncio
import os

import httpx

from reducio.llm import LLMClient
from reducio.models import AppConfig


async def check() -> None:
    real_client = httpx.AsyncClient
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

            httpx.AsyncClient = lambda **kw: real_client(
                transport=httpx.MockTransport(respond), **kw
            )
            client = LLMClient(AppConfig(llm_api=protocol, model="mock-model"))
            assert await client.complete("x = 1") == "x = 1"
            assert len(requests) == 1
    finally:
        httpx.AsyncClient = real_client
        if prior is None:
            os.environ.pop("REDUCIO_API_KEY", None)
        else:
            os.environ["REDUCIO_API_KEY"] = prior


if __name__ == "__main__":
    asyncio.run(check())
    print("Optional API client verified with mocked transports")
