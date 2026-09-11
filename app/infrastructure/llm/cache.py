import json
import time
from typing import Any

from app.infrastructure.logging import get_logger

logger = get_logger("llm.cache")


class LLMCache:
    """In-memory response cache for LLM completions with optional TTL."""

    def __init__(self, ttl_hours: int = 24) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._ttl_seconds = ttl_hours * 3600

    def _make_key(self, system: str, user: str) -> str:
        import hashlib

        content = f"{system}||{user}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, system: str, user: str) -> str | None:
        """Get cached response if available and not expired."""
        key = self._make_key(system, user)
        entry = self._cache.get(key)
        if entry is None:
            return None

        if time.time() - entry["created_at"] > self._ttl_seconds:
            del self._cache[key]
            return None

        logger.debug("llm cache hit", extra={"key": key[:12]})
        return entry["response"]

    def set(self, system: str, user: str, response: str) -> None:
        """Store a response in cache."""
        key = self._make_key(system, user)
        self._cache[key] = {
            "response": response,
            "created_at": time.time(),
        }
        logger.debug("llm cache set", extra={"key": key[:12]})

    def invalidate(self, system: str, user: str) -> None:
        """Remove a cached entry."""
        key = self._make_key(system, user)
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)

    def hit_rate(self) -> float:
        """Return cache hit rate (requires external tracking)."""
        return 0.0  # Placeholder — implement with counters if needed
