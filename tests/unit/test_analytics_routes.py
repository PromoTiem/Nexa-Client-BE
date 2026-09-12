from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.interface.auth_models import AuthContext
from app.interface.dependencies import TenantContext
from app.interface.routes.analytics import (
    _resolve_property_names,
    get_dashboard,
    get_product_analytics,
    get_top_products,
    track_event,
    track_events_batch,
)

MOCK_AUTH = AuthContext(
    token="test_token",
    record={
        "id": "user_1",
        "email": "test@example.com",
        "tenant_id": "tenant_1",
        "role": "admin",
    },
)

MOCK_MEMBER_AUTH = AuthContext(
    token="member_token",
    record={
        "id": "user_2",
        "email": "member@example.com",
        "tenant_id": "tenant_1",
        "role": "member",
    },
)

MOCK_GUEST_AUTH = AuthContext(
    token="guest_token",
    record={
        "id": "user_3",
        "email": "guest@example.com",
        "tenant_id": "tenant_1",
        "role": "guest",
    },
)


def _tenant_ctx(auth: AuthContext) -> TenantContext:
    return TenantContext(auth=auth, tenant_id=auth.record.get("tenant_id"))


def _make_collector():
    collector = AsyncMock()
    collector.record_event = AsyncMock(return_value="evt_test123")
    collector.flush = AsyncMock(return_value={"accepted": 0, "rejected": 0})
    return collector


def _mock_pb_with_records(items, total=None):
    pb = AsyncMock()
    pb.list_records = AsyncMock(
        return_value={"items": items, "totalItems": total or len(items)}
    )
    return pb


class TestTrackEventBatch:
    @pytest.mark.asyncio
    async def test_batch_track_success(self):
        pb = _mock_pb_with_records([])
        collector = _make_collector()
        from app.interface.dto.analytics import (
            AnalyticsBatchRequest,
            AnalyticsEventRequest,
        )

        body = AnalyticsBatchRequest(
            events=[
                AnalyticsEventRequest(event_type="page_view", site_id="site_1"),
            ]
        )

        result = await track_events_batch(
            body=body,
            ctx=_tenant_ctx(MOCK_AUTH),
            pb=pb,
            collector=collector,
        )

        assert result.accepted == 1
        assert result.rejected == 0

    @pytest.mark.asyncio
    async def test_batch_track_guest_forbidden(self):
        pb = _mock_pb_with_records([])
        collector = _make_collector()
        from app.interface.dto.analytics import (
            AnalyticsBatchRequest,
            AnalyticsEventRequest,
        )

        body = AnalyticsBatchRequest(
            events=[
                AnalyticsEventRequest(event_type="page_view", site_id="site_1"),
            ]
        )

        with pytest.raises(HTTPException) as exc_info:
            await track_events_batch(
                body=body,
                ctx=_tenant_ctx(MOCK_GUEST_AUTH),
                pb=pb,
                collector=collector,
            )
        assert exc_info.value.status_code == 403


class TestTrackEvent:
    @pytest.mark.asyncio
    async def test_single_track_success(self):
        pb = _mock_pb_with_records([])
        collector = _make_collector()
        from app.interface.dto.analytics import AnalyticsEventRequest

        body = AnalyticsEventRequest(event_type="page_view", site_id="site_1")

        result = await track_event(
            body=body,
            ctx=_tenant_ctx(MOCK_AUTH),
            pb=pb,
            collector=collector,
        )

        assert result.event_id == "evt_test123"
        assert result.accepted is True


class TestGetDashboard:
    @pytest.mark.asyncio
    async def test_returns_dashboard_with_kpis(self):
        aggs = [
            {
                "total_views": 100,
                "unique_visitors": 50,
                "product_views": 30,
                "product_impressions": 20,
                "add_to_carts": 10,
                "purchases": 5,
                "revenue": 250.0,
                "search_count": 8,
                "avg_session_duration": 60.0,
                "pages_per_session": 2.5,
            }
        ]
        pb = _mock_pb_with_records(aggs)
        collector = _make_collector()

        result = await get_dashboard(
            site_id="site_1",
            range="30d",
            ctx=_tenant_ctx(MOCK_AUTH),
            pb=pb,
            collector=collector,
        )

        assert result.site_id == "site_1"
        assert result.kpis.total_views == 100
        assert result.kpis.revenue == 250.0
        assert result.kpis.avg_session_duration == 60.0

    @pytest.mark.asyncio
    async def test_dashboard_resolves_property_names(self):
        aggs = [
            {
                "total_views": 100,
                "unique_visitors": 0,
                "product_views": 0,
                "product_impressions": 0,
                "add_to_carts": 0,
                "purchases": 0,
                "revenue": 0,
                "search_count": 0,
                "avg_session_duration": None,
                "pages_per_session": None,
            }
        ]
        top_prop = [
            {"property_id": "prop_1", "views": 100, "bookings": 0, "revenue": 0.0}
        ]
        props = [{"property_id": "prop_1", "name": "Test Product"}]

        pb = AsyncMock()

        async def side_effect(*args, **kwargs):
            collection = args[0] if args else ""
            # Properties collection lookup
            if collection == "properties":
                return {"items": props, "totalItems": 1}
            # Aggregates queries
            return {"items": aggs, "totalItems": 1}

        # get_top_properties calls _query_aggregates with include_properties=True
        # which means property_id="" filter is NOT added, so it returns all aggs including top_prop
        async def list_records_side_effect(*args, **kwargs):
            filter_val = kwargs.get("filter", "")
            collection = args[0] if args else ""
            if collection == "properties":
                return {"items": props, "totalItems": 1}
            # For aggregates: if include_properties is True (no property_id="" filter), return top data
            if "property_id=" not in filter_val:
                return {"items": top_prop, "totalItems": 1}
            return {"items": aggs, "totalItems": 1}

        pb.list_records = AsyncMock(side_effect=list_records_side_effect)
        collector = _make_collector()

        result = await get_dashboard(
            site_id="site_1",
            range="30d",
            ctx=_tenant_ctx(MOCK_AUTH),
            pb=pb,
            collector=collector,
        )

        assert len(result.top_services) == 1
        assert result.top_services[0].name == "Test Product"


class TestGetTopProducts:
    @pytest.mark.asyncio
    async def test_returns_top_products_with_names(self):
        top_raw = [
            {"property_id": "p1", "views": 100, "bookings": 10, "revenue": 500.0},
            {"property_id": "p2", "views": 50, "bookings": 5, "revenue": 200.0},
        ]
        props = [
            {"property_id": "p1", "name": "Product A"},
            {"property_id": "p2", "name": "Product B"},
        ]

        pb = AsyncMock()

        async def side_effect(*args, **kwargs):
            filter_val = kwargs.get("filter", args[2] if len(args) > 2 else "")
            if "property_id=" in filter_val:
                return {"items": props, "totalItems": 2}
            return {"items": top_raw, "totalItems": 2}

        pb.list_records = AsyncMock(side_effect=side_effect)
        collector = _make_collector()

        result = await get_top_products(
            site_id="site_1",
            range="30d",
            metric="views",
            limit=10,
            ctx=_tenant_ctx(MOCK_AUTH),
            pb=pb,
            collector=collector,
        )

        assert len(result.items) == 2
        assert result.items[0].name == "Product A"
        assert result.items[1].name == "Product B"


class TestGetProductAnalytics:
    @pytest.mark.asyncio
    async def test_returns_product_analytics_with_name(self):
        kpis = [
            {
                "total_views": 50,
                "unique_visitors": 25,
                "product_views": 20,
                "product_impressions": 10,
                "add_to_carts": 5,
                "purchases": 2,
                "revenue": 100.0,
                "search_count": 3,
                "avg_session_duration": 45.0,
                "pages_per_session": 2.0,
            }
        ]
        props = [{"property_id": "prop_1", "name": "My Product"}]

        pb = AsyncMock()

        async def side_effect(*args, **kwargs):
            collection = args[0] if args else ""
            filter_val = kwargs.get("filter", "")
            if collection == "properties":
                return {"items": props, "totalItems": 1}
            if "total_views" in filter_val:
                return {"items": kpis, "totalItems": 1}
            # For trend queries (sorted by date)
            return {
                "items": [
                    {
                        "date": "2026-01-01",
                        "site_id": "site_1",
                        "property_id": "prop_1",
                        "total_views": 50,
                        "unique_visitors": 0,
                        "product_views": 0,
                        "product_impressions": 0,
                        "add_to_carts": 0,
                        "purchases": 0,
                        "revenue": 0,
                        "search_count": 0,
                        "avg_session_duration": None,
                        "pages_per_session": None,
                    }
                ],
                "totalItems": 1,
            }

        pb.list_records = AsyncMock(side_effect=side_effect)
        collector = _make_collector()

        result = await get_product_analytics(
            site_id="site_1",
            property_id="prop_1",
            range="30d",
            ctx=_tenant_ctx(MOCK_AUTH),
            pb=pb,
            collector=collector,
        )

        assert result.name == "My Product"
        assert result.kpis.total_views == 50


class TestResolvePropertyNames:
    @pytest.mark.asyncio
    async def test_returns_empty_map_for_empty_input(self):
        pb = AsyncMock()
        result = await _resolve_property_names(pb, "site_1", [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_batch_fetches_names(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(
            return_value={
                "items": [
                    {"property_id": "p1", "name": "Product A"},
                    {"property_id": "p2", "name": "Product B"},
                ],
                "totalItems": 2,
            }
        )

        result = await _resolve_property_names(pb, "site_1", ["p1", "p2"])

        assert result == {"p1": "Product A", "p2": "Product B"}

    @pytest.mark.asyncio
    async def test_falls_back_to_property_id_on_error(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(side_effect=Exception("PB error"))

        result = await _resolve_property_names(pb, "site_1", ["p1", "p2"])

        assert result == {"p1": "p1", "p2": "p2"}
