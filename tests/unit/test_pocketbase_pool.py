from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.infrastructure.pocketbase.client import PocketBaseClient


async def test_shared_pool_keeps_tokens_per_request_and_stays_open():
    seen = []

    async def respond(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        first = PocketBaseClient("http://pb", http_client=transport)
        second = PocketBaseClient(
            "http://pb", static_token="service-token", http_client=transport
        )
        await first.list_records("sites", token="tenant-a")
        await first.list_records("sites", token="tenant-b")
        await second.list_records("sites")
        assert not transport.is_closed
        assert "authorization" not in transport.headers
    assert seen == ["Bearer tenant-a", "Bearer tenant-b", "Bearer service-token"]
    assert transport.is_closed


async def test_lifespan_closes_pool_on_failure(monkeypatch):
    import app.main as main

    @asynccontextmanager
    async def application(app):
        yield

    monkeypatch.setattr(main, "_application_lifespan", application)
    app = FastAPI()
    try:
        async with main.lifespan(app):
            transport = app.state.pocketbase_http
            assert not transport.is_closed
            raise RuntimeError("shutdown")
    except RuntimeError:
        pass
    assert transport.is_closed
    assert not hasattr(app.state, "pocketbase_http")


async def test_concurrent_callers_keep_their_own_authorization():
    import asyncio

    arrived = 0
    ready = asyncio.Event()

    async def respond(request):
        nonlocal arrived
        arrived += 1
        if arrived == 20:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=2)
        return httpx.Response(200, json={"token": request.headers["authorization"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        clients = [
            PocketBaseClient("http://pb", http_client=transport) for _ in range(20)
        ]
        responses = await asyncio.gather(
            *(
                client.find_record_by_id("sites", "site", token=f"caller-{i}")
                for i, client in enumerate(clients)
            )
        )
        assert [r["token"] for r in responses] == [
            f"Bearer caller-{i}" for i in range(20)
        ]
        assert "authorization" not in transport.headers


async def test_dependency_borrows_pool_through_fastapi():
    from fastapi import Depends

    from app.interface.dependencies import get_pocketbase_client

    app = FastAPI()

    @app.get("/probe")
    async def probe(pb: PocketBaseClient = Depends(get_pocketbase_client)):
        return {"shared": pb._http_client is app.state.pocketbase_http}

    async with httpx.AsyncClient() as pool:
        app.state.pocketbase_http = pool
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as caller:
            response = await caller.get("/probe")
        assert response.status_code == 200
        assert response.json() == {"shared": True}
        assert not pool.is_closed


async def test_lifespan_closes_pool_when_startup_fails(monkeypatch):
    import pytest

    import app.main as main

    pools = []

    @asynccontextmanager
    async def application(app):
        pools.append(app.state.pocketbase_http)
        raise RuntimeError("startup failed")
        yield

    monkeypatch.setattr(main, "_application_lifespan", application)
    app = FastAPI()
    with pytest.raises(RuntimeError, match="startup failed"):
        async with main.lifespan(app):
            raise AssertionError("startup must fail")
    assert pools[0].is_closed
    assert not hasattr(app.state, "pocketbase_http")


async def test_standalone_client_owns_and_closes_transport():
    pb = PocketBaseClient("http://pb")
    async with pb._client() as transport:
        assert not transport.is_closed
    assert transport.is_closed
