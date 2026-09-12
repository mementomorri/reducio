"""Optional explicit API support (HTTP dependencies load only on a request)."""

from reducio.llm.router import LLMClient, LLMError

__all__ = ["LLMClient", "LLMError"]
