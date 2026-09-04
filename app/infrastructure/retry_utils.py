from collections.abc import Callable
from typing import Any

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.infrastructure.logging import get_logger

logger = get_logger("retry_utils")

HTTP_RETRY_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
)


def is_retryable_response(response: httpx.Response) -> bool:
    return response.status_code >= 500 or response.status_code == 429


def get_retry_reason(retry_state) -> str:
    if retry_state.outcome.failed:
        return str(retry_state.outcome.exception())
    result = retry_state.outcome.result()
    if isinstance(result, httpx.Response):
        return f"5xx ({result.status_code})"
    return "unknown"


def make_retry_decorator(
    max_retries: int,
    backoff: float,
    max_jitter: int,
    service: str,
    retry_exceptions: tuple[type[Exception], ...] = HTTP_RETRY_EXCEPTIONS,
    retry_on_result: bool = True,
    extra_context: str | None = None,
) -> Callable:
    retry_condition = retry_if_exception_type(retry_exceptions)
    if retry_on_result:
        retry_condition = retry_condition | retry_if_result(is_retryable_response)

    def before_sleep(retry_state) -> None:
        log_data = {
            "operation": extra_context or service,
            "attempt": retry_state.attempt_number,
            "reason": get_retry_reason(retry_state),
        }
        if extra_context:
            log_data["service"] = service
        logger.warning(f"{service} retrying", extra=log_data)

    return retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential_jitter(initial=backoff, max=max_jitter),
        retry=retry_condition,
        before_sleep=before_sleep,
        reraise=False,
    )


async def execute_with_retry(
    retry_decorator: Callable,
    request_fn: Callable[..., Any],
    **kwargs: Any,
) -> Any:
    @retry_decorator
    async def _wrapped() -> Any:
        return await request_fn(**kwargs)

    try:
        return await _wrapped()
    except RetryError as exc:
        last_attempt = exc.last_attempt
        if last_attempt.failed:
            raise last_attempt.exception()
        return last_attempt.result()
