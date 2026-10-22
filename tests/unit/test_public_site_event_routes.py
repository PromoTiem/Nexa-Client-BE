from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.infrastructure.rate_limits import get_limiter
from app.interface.dependencies import (
    get_analytics_collector,
    get_static_pocketbase_client,
)
from app.interface.exception_handlers import register_exception_handlers
from app.interface.routes.property import public_property_router

SITE = {
    "site_id": "site",
    "tenant_id": "tenant",
    "config": {
        "public_submissions": {"enabled": True, "types": ["newsletter_subscription"]}
    },
}


def _app(pb, collector):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(public_property_router, prefix="/public")
    app.dependency_overrides[get_static_pocketbase_client] = lambda: pb
    app.dependency_overrides[get_analytics_collector] = lambda: collector
    app.dependency_overrides[get_settings] = lambda: Settings(
        rate_limit_storage_uri="memory://"
    )
    get_limiter("memory://").storage.reset()
    return app


async def test_public_event_route_records_without_auth():
    pb, collector = AsyncMock(), AsyncMock()
    pb.find_one_by_filter.return_value = SITE
    collector.record_event.return_value = "evt_1"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(pb, collector)), base_url="http://t"
    ) as c:
        res = await c.post(
            "/public/analytics/events",
            json={"site_id": "site", "event_type": "page_view"},
        )
    assert res.status_code == 202
    assert res.json() == {"accepted": True}
    collector.record_event.assert_awaited_once()


async def test_public_event_route_rejects_untrusted_types():
    pb, collector = AsyncMock(), AsyncMock()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(pb, collector)), base_url="http://t"
    ) as c:
        res = await c.post(
            "/public/analytics/events",
            json={"site_id": "site", "event_type": "purchase"},
        )
    assert res.status_code == 422
    collector.record_event.assert_not_awaited()


async def test_subscription_route_answers_the_same_for_new_and_repeat_addresses():
    pb, collector = AsyncMock(), AsyncMock()
    pb.find_one_by_filter.return_value = SITE
    pb.list_records.side_effect = [{"items": []}, {"items": [{"property_id": "sub_x"}]}]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(pb, collector)), base_url="http://t"
    ) as c:
        first = await c.post(
            "/public/sites/site/subscriptions", json={"email": "guest@example.com"}
        )
        again = await c.post(
            "/public/sites/site/subscriptions", json={"email": "guest@example.com"}
        )
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json() == {"accepted": True}
    assert pb.create_record.await_count == 1


async def test_subscription_route_rate_limits_by_address():
    pb, collector = AsyncMock(), AsyncMock()
    pb.find_one_by_filter.return_value = SITE
    pb.list_records.return_value = {"items": [{"property_id": "sub_x"}]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(pb, collector)), base_url="http://t"
    ) as c:
        codes = [
            (
                await c.post(
                    "/public/sites/site/subscriptions",
                    json={"email": f"g{i}@example.com"},
                )
            ).status_code
            for i in range(6)
        ]
    assert codes[:5] == [202] * 5
    assert codes[5] == 429
