import json
from typing import Any

import httpx

from app.config import LLMSettings
from app.infrastructure.llm.cache import LLMCache
from app.infrastructure.llm.token_tracker import TokenTracker
from app.infrastructure.logging import get_logger
from app.infrastructure.retry_utils import execute_with_retry, make_retry_decorator

logger = get_logger("llm.client")

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class LLMClient:
    """OpenAI GPT-4o-mini wrapper with caching + budget enforcement."""

    def __init__(
        self,
        settings: LLMSettings,
        cache: LLMCache | None = None,
        token_tracker: TokenTracker | None = None,
    ) -> None:
        self._settings = settings
        self._cache = cache or LLMCache(ttl_hours=settings.cache_ttl_hours)
        self._tracker = token_tracker or TokenTracker(monthly_budget_usd=settings.monthly_budget_usd)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
        )
        self._retry = make_retry_decorator(
            max_retries=2,
            backoff=1.0,
            max_jitter=5,
            service="llm",
        )

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        """Single completion with cache check + budget guard."""
        if not self._settings.enabled:
            raise RuntimeError("LLM is disabled")

        # Check cache
        cached = self._cache.get(system, user)
        if cached is not None:
            return cached

        # Check budget
        if not self._tracker.can_afford():
            logger.warning("llm budget exceeded, skipping")
            raise RuntimeError("LLM monthly budget exceeded")

        model = model or self._settings.model
        temp = temperature if temperature is not None else self._settings.temperature
        max_tok = max_tokens or self._settings.max_tokens

        # Call OpenAI
        response = await self._call_openai(system, user, model, temp, max_tok)
        content = response["choices"][0]["message"]["content"]

        # Track usage
        usage = response.get("usage", {})
        self._tracker.record_usage(
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

        # Cache
        self._cache.set(system, user, content)

        return content

    async def complete_batch(
        self,
        system: str,
        items: list[str],
        **kwargs: Any,
    ) -> list[str]:
        """Batch completion — multiple items in one prompt to save tokens."""
        combined_user = "\n\n---\n\n".join(
            f"Item {i + 1}:\n{item}" for i, item in enumerate(items)
        )
        result = await self.complete(system, combined_user, **kwargs)

        # Try to parse as JSON array
        try:
            parsed = json.loads(result)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback: split by separator
        return [result]

    async def structured_output(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Completion with JSON output."""
        json_system = f"{system}\n\nYou MUST respond with valid JSON only. No markdown, no explanation."
        result = await self.complete(json_system, user, model=model)

        # Clean up potential markdown code blocks
        cleaned = result.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("llm JSON parse failed", extra={"error": str(e), "response": cleaned[:200]})
            return {"error": "Failed to parse LLM response", "raw": cleaned}

    async def _call_openai(
        self,
        system: str,
        user: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Call OpenAI API directly with httpx."""
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        @self._retry
        async def _request() -> httpx.Response:
            return await self._client.post(OPENAI_API_URL, json=payload, headers=headers)

        response = await _request()

        if response.status_code != 200:
            error_msg = f"OpenAI API error {response.status_code}: {response.text[:500]}"
            logger.error("openai api error", extra={"status": response.status_code, "error": response.text[:200]})
            raise RuntimeError(error_msg)

        return response.json()

    @property
    def cache(self) -> LLMCache:
        return self._cache

    @property
    def tracker(self) -> TokenTracker:
        return self._tracker

    async def close(self) -> None:
        await self._client.aclose()
