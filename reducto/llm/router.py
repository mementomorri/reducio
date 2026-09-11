"""LLM router for model selection and completion."""

import logging
from typing import Any

import httpx
import litellm
from litellm import acompletion

from reducto.models import ModelTier

logger = logging.getLogger(__name__)


class LLMRouter:
    """Routes LLM requests to appropriate models based on tier."""

    def __init__(
        self,
        config: dict[str, dict[str, Any]] | None = None,
        verbose: bool = False,
        model_override: str | None = None,
        prefer_local: bool = True,
    ):
        self.config = config or self._default_config()
        self._local_available: bool | None = None
        self.verbose = verbose
        self.model_override = model_override
        self.prefer_local = prefer_local
        self._setup_litellm()

    def _default_config(self) -> dict[str, dict[str, Any]]:
        return {
            "light": {
                "local_model": "ollama/gemma3:270m",
                "remote_model": "openai/gpt-4o-mini",
            },
            "medium": {
                "local_model": "ollama/qwen2.5-coder:1.5b",
                "remote_model": "anthropic/claude-3-haiku-20240307",
            },
            "heavy": {
                "local_model": "ollama/deepseek-coder:6.7b",
                "remote_model": "anthropic/claude-3-5-sonnet-20241022",
            },
        }

    def _setup_litellm(self):
        """Configure LiteLLM with API keys and settings."""
        # CLI verbosity must not enable provider debug dumps containing source or secrets.
        litellm.set_verbose = False
        litellm.suppress_debug_info = True
        litellm.drop_params = True

    def is_local_available(self) -> bool:
        """Check if Ollama is running locally."""
        if self._local_available is not None:
            return self._local_available

        try:
            response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
            self._local_available = response.status_code == 200
            if self.verbose:
                logger.info(f"Ollama availability check: {self._local_available}")
        except Exception as e:
            self._local_available = False
            if self.verbose:
                logger.info(f"Ollama not available: {e}")

        return self._local_available

    def get_model_for_tier(
        self, tier: ModelTier, prefer_local: bool | None = None, model_override: str | None = None
    ) -> str:
        """Resolve a model id for a tier; an override bypasses tier selection."""
        actual_model_override = model_override or self.model_override
        actual_prefer_local = prefer_local if prefer_local is not None else self.prefer_local

        if actual_model_override:
            if self.verbose:
                logger.info("Using the selected model")
            return actual_model_override

        cfg = self.config.get(tier.value, {})

        if actual_prefer_local and self.is_local_available():
            model = cfg.get("local_model", cfg.get("remote_model", ""))
            source = "local"
        else:
            model = cfg.get("remote_model", cfg.get("local_model", ""))
            source = "remote"

        if not model:
            raise ValueError(f"No model configured for tier {tier}")

        if self.verbose:
            logger.info(
                f"Model selection: tier={tier.value}, "
                f"prefer_local={actual_prefer_local}, source={source}, model={model}"
            )

        return str(model)

    async def complete(
        self,
        prompt: str,
        tier: ModelTier = ModelTier.MEDIUM,
        system_prompt: str | None = None,
        prefer_local: bool | None = None,
        model_override: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """Generate a completion with the tier's (or overridden) model."""
        actual_prefer_local = prefer_local if prefer_local is not None else self.prefer_local
        actual_model_override = model_override or self.model_override
        model = self.get_model_for_tier(tier, actual_prefer_local, actual_model_override)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        if self.verbose:
            logger.info(f"LLM request: tier={tier.value}")

        try:
            response = await acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            content = response.choices[0].message.content

            if self.verbose:
                usage = getattr(response, "usage", None)
                if usage:
                    logger.info(
                        f"LLM response: tokens_prompt={usage.prompt_tokens}, tokens_completion={usage.completion_tokens}"
                    )

            return content if isinstance(content, str) else ""
        except Exception:
            logger.error("LLM call failed; provider details withheld")
            raise
