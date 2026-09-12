"""Explicit text-only OpenAI/Anthropic-compatible APIs; no discovery or routing."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit

from reducio.models import AppConfig


class LLMError(RuntimeError):
    """Only sanitized, user-actionable messages may cross the API boundary."""


class LLMClient:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg.model_copy(deep=True)

    async def complete(self, prompt: str, system_prompt: str | None = None) -> str:
        cfg = self.cfg
        if not cfg.llm_api or not cfg.model.strip():
            raise LLMError("Set llm_api (openai or anthropic) and an explicit model")
        key_name = "OPENAI_API_KEY" if cfg.llm_api == "openai" else "ANTHROPIC_API_KEY"
        token = os.environ.get("REDUCIO_API_KEY") or os.environ.get(key_name)
        if not token or not token.strip():
            raise LLMError(f"Set REDUCIO_API_KEY or {key_name}")
        base = cfg.llm_base_url or (
            "https://api.openai.com/v1"
            if cfg.llm_api == "openai"
            else "https://api.anthropic.com/v1"
        )
        try:
            url = urlsplit(base)
            if (
                not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or (
                    url.scheme != "https"
                    and not (
                        url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
                    )
                )
            ):
                raise ValueError()
            url.port  # Reject malformed ports without echoing the URL.
        except ValueError:
            raise LLMError(
                "Use an HTTPS API base URL without credentials/query/fragment; HTTP is loopback-only"
            ) from None
        try:
            import httpx
        except ImportError:
            raise LLMError('Install optional API support: pip install "reducio[llm]"') from None

        body: dict = {
            "model": cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if cfg.llm_api == "openai":
            endpoint = "chat/completions"
            headers["Authorization"] = f"Bearer {token}"
            body["max_completion_tokens"] = cfg.llm_max_tokens
            if system_prompt:
                body["messages"].insert(0, {"role": "system", "content": system_prompt})
        else:
            endpoint = "messages"
            headers.update({"x-api-key": token, "anthropic-version": "2023-06-01"})
            body["max_tokens"] = cfg.llm_max_tokens
            if system_prompt:
                body["system"] = system_prompt
        try:
            async with asyncio.timeout(cfg.llm_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=cfg.llm_timeout_seconds, follow_redirects=False
                ) as client:
                    response = await client.post(
                        base.rstrip("/") + "/" + endpoint, headers=headers, json=body
                    )
                    if not response.is_success:
                        raise LLMError(
                            f"API request failed (HTTP {response.status_code}); check endpoint, model and credentials"
                        )
                    data = response.json()
            if cfg.llm_api == "openai":
                choice = data["choices"][0]
                if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
                    raise LLMError(
                        "API response was truncated, refused or not a completed text reply"
                    )
                text = choice["message"]["content"]
            else:
                if data["stop_reason"] != "end_turn":
                    raise LLMError(
                        "API response was truncated, refused or not a completed text reply"
                    )
                blocks = data["content"]
                if not isinstance(blocks, list) or not all(b.get("type") == "text" for b in blocks):
                    raise LLMError("API response was not a completed text reply")
                text = "\n".join(b["text"] for b in blocks)
            if not isinstance(text, str) or not text.strip():
                raise LLMError("API returned an empty text reply")
            if token in text:
                raise LLMError("API response contained credentials; reply discarded")
            return text
        except LLMError:
            raise
        except TimeoutError, httpx.TimeoutException:
            raise LLMError("API request timed out") from None
        except Exception:
            raise LLMError(
                "API request failed or returned malformed data; provider details withheld"
            ) from None
