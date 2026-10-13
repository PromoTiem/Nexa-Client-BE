"""Reload site-owned records under lifecycle locks before mutating them."""

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import HTTPException

from app.infrastructure.operation_lock import operation_lock


@asynccontextmanager
async def locked_record(pb, collection, predicate, token, *, build=False):
    async def load():
        return await pb.find_one_by_filter(
            collection=collection, filter_expr=predicate, token=token
        )

    before = await load()
    site_id = before.get("site_id")
    if not site_id:
        raise HTTPException(404, "Parent site not found")
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(operation_lock(f"site:{site_id}"))
        if build:
            await stack.enter_async_context(operation_lock("build-lifecycle"))
        current = await load()
        if current.get("site_id") != site_id or current.get("id") != before.get("id"):
            raise HTTPException(409, "Record changed; retry the request")
        yield current
