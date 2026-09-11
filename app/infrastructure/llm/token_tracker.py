import json
import time
from typing import Any

from app.infrastructure.logging import get_logger

logger = get_logger("llm.token_tracker")


class TokenTracker:
    """Track LLM token usage and costs."""

    # Pricing per 1M tokens (USD)
    PRICING: dict[str, dict[str, float]] = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "claude-3-5-haiku": {"input": 0.25, "output": 1.25},
    }

    def __init__(self, monthly_budget_usd: float = 50.0) -> None:
        self._monthly_budget = monthly_budget_usd
        self._total_tokens = 0
        self._total_cost = 0.0
        self._calls: list[dict[str, Any]] = []
        self._month_start = self._current_month()

    def _current_month(self) -> str:
        return time.strftime("%Y-%m")

    def _reset_if_new_month(self) -> None:
        current = self._current_month()
        if current != self._month_start:
            logger.info(
                "token tracker month rollover",
                extra={"prev_month": self._month_start, "new_month": current, "cost": self._total_cost},
            )
            self._total_tokens = 0
            self._total_cost = 0.0
            self._calls.clear()
            self._month_start = current

    def record_usage(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Record token usage and return the cost."""
        self._reset_if_new_month()

        pricing = self.PRICING.get(model, self.PRICING["gpt-4o-mini"])
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        self._total_tokens += input_tokens + output_tokens
        self._total_cost += cost
        self._calls.append(
            {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
                "timestamp": time.time(),
            }
        )

        logger.debug(
            "llm token usage",
            extra={"model": model, "input": input_tokens, "output": output_tokens, "cost": cost},
        )
        return cost

    def can_afford(self, estimated_tokens: int = 1000) -> bool:
        """Check if we can afford an estimated call."""
        self._reset_if_new_month()
        if self._monthly_budget <= 0:
            return True

        pricing = self.PRICING["gpt-4o-mini"]
        estimated_cost = (estimated_tokens * pricing["input"]) / 1_000_000
        return (self._total_cost + estimated_cost) <= self._monthly_budget

    @property
    def spent_usd(self) -> float:
        self._reset_if_new_month()
        return self._total_cost

    @property
    def remaining_usd(self) -> float:
        self._reset_if_new_month()
        if self._monthly_budget <= 0:
            return float("inf")
        return max(0.0, self._monthly_budget - self._total_cost)

    @property
    def usage_pct(self) -> float:
        self._reset_if_new_month()
        if self._monthly_budget <= 0:
            return 0.0
        return (self._total_cost / self._monthly_budget) * 100

    @property
    def total_calls(self) -> int:
        return len(self._calls)
