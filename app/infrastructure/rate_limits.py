import asyncio
from functools import lru_cache

from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter


@lru_cache
def get_limiter(uri: str) -> MovingWindowRateLimiter:
    return MovingWindowRateLimiter(storage_from_string(uri))


async def allow_request(uri: str, quota: str, scope: str, identity: str) -> bool:
    return await asyncio.to_thread(get_limiter(uri).hit, parse(quota), scope, identity)
