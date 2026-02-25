"""
Unified LLM client using litellm + instructor for structured output.

Configuration (via Settings / .env):
  LLM_MODEL      — e.g. "ollama/llama3.1:8b" (default, free local)
  LLM_BASE_URL   — Ollama base URL ("http://localhost:11434")
  LLM_TEMPERATURE — Default temperature (0.1 for deterministic extraction)
  LLM_MAX_TOKENS  — Max output tokens per call
"""
import logging
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
_TIKTOKEN_ENCODING = "cl100k_base"


class LLMClient:
    """
    Provider-agnostic LLM client using litellm for routing.

    Uses instructor to patch the completion call so the LLM is forced
    to return output that validates against the given Pydantic schema
    (retries automatically on bad/non-conforming output).

    Supports Ollama (local/free), OpenAI, Anthropic, and any litellm provider.
    """

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings

            settings = get_settings()

        self.model: str = settings.llm_model
        self.base_url: Optional[str] = settings.llm_base_url or None
        self.temperature: float = settings.llm_temperature
        self.max_tokens: int = settings.llm_max_tokens
        self._client = None  # lazy-initialised

    def _get_client(self):
        """Lazily create and cache the instructor-patched litellm async client."""
        if self._client is None:
            import instructor
            import litellm

            litellm.set_verbose = False
            self._client = instructor.from_litellm(
                litellm.acompletion,
                mode=instructor.Mode.JSON,
            )
        return self._client

    async def extract_structured(
        self,
        content: str,
        response_model: Type[T],
        system_prompt: str = "",
        temperature: Optional[float] = None,
        max_retries: int = 3,
    ) -> T:
        """
        Send content to the LLM and return a validated Pydantic object.

        instructor guarantees schema compliance by retrying on bad output.
        """
        client = self._get_client()

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})

        kwargs: dict = {
            "model": self.model,
            "response_model": response_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_retries": max_retries,
        }
        if self.base_url:
            kwargs["api_base"] = self.base_url

        logger.debug(
            "LLM call: model=%s, approx_tokens=%d", self.model, len(content) // 4
        )
        return await client.chat.completions.create(**kwargs)

    def count_tokens(self, text: str) -> int:
        """Count tokens for cost / context-window tracking."""
        try:
            import tiktoken

            enc = tiktoken.get_encoding(_TIKTOKEN_ENCODING)
            return len(enc.encode(text))
        except Exception:
            return max(1, len(text) // 4)
