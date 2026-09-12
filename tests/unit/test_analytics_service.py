from unittest.mock import AsyncMock

import pytest

from app.application.services.analytics_service import AnalyticsService
from app.infrastructure.analytics.aggregator import AnalyticsAggregator
from app.infrastructure.analytics.collector import AnalyticsCollector


def _make_service(pb=None):
    pb = pb or AsyncMock()
    collector = AsyncMock(spec=AnalyticsCollector)
    collector.record_event = AsyncMock(return_value="evt_test123")
    collector.flush = AsyncMock(return_value={"accepted": 0, "rejected": 0})
    aggregator = AnalyticsAggregator(pb)
    return AnalyticsService(
        collector=collector, aggregator=aggregator, pb=pb, token="test_token"
    ), collector


class TestAnalyticsServiceTrackEvent:
    @pytest.mark.asyncio
    async def test_delegates_to_collector(self):
        service, collector = _make_service()

        event_id = await service.track_event(
            event_type="page_view",
            site_id="site_1",
            property_id="prop_1",
            tenant_id="tenant_1",
            session_id="sess_1",
            metadata={"key": "val"},
            user_agent="Mozilla/5.0",
        )

        assert event_id == "evt_test123"
        collector.record_event.assert_called_once_with(
            event_type="page_view",
            site_id="site_1",
            property_id="prop_1",
            tenant_id="tenant_1",
            session_id="sess_1",
            metadata={"key": "val"},
            user_agent="Mozilla/5.0",
            timestamp=None,
        )


class TestAnalyticsServiceTrackBatch:
    @pytest.mark.asyncio
    async def test_counts_accepted_and_rejected(self):
        service, collector = _make_service()
        call_count = 0

        async def track_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("track failed")
            return "evt_ok"

        collector.record_event = AsyncMock(side_effect=track_side_effect)

        events = [
            {"event_type": "page_view", "site_id": "s1"},
            {"event_type": "page_view", "site_id": "s1"},
            {"event_type": "page_view", "site_id": "s1"},
        ]
        result = await service.track_batch(events)

        assert result["accepted"] == 2
        assert result["rejected"] == 1


class TestAnalyticsServiceGetKpis:
    @pytest.mark.asyncio
    async def test_returns_zeros_when_no_aggregates(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(return_value={"items": [], "totalItems": 0})
        service, _ = _make_service(pb)

        result = await service.get_kpis("site_1", "2026-01-01", "2026-01-31")

        assert result["total_views"] == 0
        assert result["revenue"] == 0.0
        assert result["avg_session_duration"] is None

    @pytest.mark.asyncio
    async def test_sums_multiple_days(self):
        pb = AsyncMock()
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
                "avg_session_duration": 120.0,
                "pages_per_session": 3.0,
            },
            {
                "total_views": 200,
                "unique_visitors": 80,
                "product_views": 60,
                "product_impressions": 40,
                "add_to_carts": 20,
                "purchases": 10,
                "revenue": 500.0,
                "search_count": 15,
                "avg_session_duration": 90.0,
                "pages_per_session": 4.0,
            },
        ]
        pb.list_records = AsyncMock(return_value={"items": aggs, "totalItems": 2})
        service, _ = _make_service(pb)

        result = await service.get_kpis("site_1", "2026-01-01", "2026-01-02")

        assert result["total_views"] == 300
        assert result["unique_visitors"] == 130
        assert result["product_impressions"] == 60
        assert result["bookings"] == 30
        assert result["orders"] == 15
        assert result["revenue"] == 750.0
        assert result["search_count"] == 23
        assert result["conversion_rate"] == 5.0  # 15/300*100
        assert result["avg_order_value"] == 50.0  # 750/15
        assert result["avg_session_duration"] == 105.0
        assert result["pages_per_session"] == 3.5


class TestAnalyticsServiceGetTrend:
    @pytest.mark.asyncio
    async def test_returns_time_series(self):
        pb = AsyncMock()
        aggs = [
            {"date": "2026-01-01", "total_views": 100},
            {"date": "2026-01-02", "total_views": 200},
            {"date": "2026-01-03", "total_views": 150},
        ]
        pb.list_records = AsyncMock(return_value={"items": aggs, "totalItems": 3})
        service, _ = _make_service(pb)

        result = await service.get_trend(
            "site_1", "views_trend", "2026-01-01", "2026-01-03"
        )

        assert len(result) == 3
        assert result[0] == {"date": "2026-01-01", "value": 100}
        assert result[1] == {"date": "2026-01-02", "value": 200}
        assert result[2] == {"date": "2026-01-03", "value": 150}

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_metric(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(return_value={"items": [], "totalItems": 0})
        service, _ = _make_service(pb)

        result = await service.get_trend(
            "site_1", "unknown_metric", "2026-01-01", "2026-01-01"
        )

        assert result == []


class TestAnalyticsServiceGetKpisChange:
    @pytest.mark.asyncio
    async def test_computes_percentage_change(self):
        pb = AsyncMock()
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Current period
                return {
                    "items": [
                        {
                            "total_views": 200,
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
            # Previous period
            return {
                "items": [
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
                ],
                "totalItems": 1,
            }

        pb.list_records = AsyncMock(side_effect=side_effect)
        service, _ = _make_service(pb)

        result = await service.get_kpis_change("site_1", "30d")

        assert result["total_views"] == 100.0  # (200-100)/100*100


class TestAnalyticsServiceDateRange:
    def test_7d(self):
        service, _ = _make_service()
        start, end = service._date_range("7d")
        assert len(start) == 10
        assert len(end) == 10

    def test_30d(self):
        service, _ = _make_service()
        start, _end = service._date_range("30d")
        assert len(start) == 10

    def test_all(self):
        service, _ = _make_service()
        start, _end = service._date_range("all")
        assert start == "2020-01-01"

    def test_previous_period_range(self):
        service, _ = _make_service()
        # Period 2026-01-11 to 2026-01-31 is 20 days
        # Previous period of equal length ends day before start: 2025-12-21 to 2026-01-10
        prev_start, prev_end = service._previous_period_range(
            "2026-01-11", "2026-01-31"
        )
        assert prev_start == "2025-12-21"
        assert prev_end == "2026-01-10"


class TestAnalyticsServiceGetBreakdown:
    @pytest.mark.asyncio
    async def test_traffic_sources_breakdown(self):
        pb = AsyncMock()
        aggs = [
            {"property_id": "", "traffic_sources": {"search": 10, "direct": 5}},
            {"property_id": "", "traffic_sources": {"search": 3, "social": 7}},
        ]
        pb.list_records = AsyncMock(return_value={"items": aggs, "totalItems": 2})
        service, _ = _make_service(pb)

        result = await service.get_breakdown(
            "site_1", "traffic_sources", "2026-01-01", "2026-01-01"
        )

        assert len(result) == 3
        labels = [r["label"] for r in result]
        assert "search" in labels
        assert "direct" in labels
        assert "social" in labels

    @pytest.mark.asyncio
    async def test_device_breakdown(self):
        pb = AsyncMock()
        aggs = [
            {"property_id": "", "device_types": {"desktop": 20, "mobile": 15}},
        ]
        pb.list_records = AsyncMock(return_value={"items": aggs, "totalItems": 1})
        service, _ = _make_service(pb)

        result = await service.get_breakdown(
            "site_1", "device_breakdown", "2026-01-01", "2026-01-01"
        )

        assert len(result) == 2
        assert result[0]["label"] == "desktop"
        assert result[0]["value"] == 20

    @pytest.mark.asyncio
    async def test_property_breakdown(self):
        pb = AsyncMock()
        aggs = [
            {"property_id": "prop_1", "total_views": 100},
            {"property_id": "prop_2", "total_views": 200},
            {"property_id": "", "total_views": 50},
        ]
        pb.list_records = AsyncMock(return_value={"items": aggs, "totalItems": 3})
        service, _ = _make_service(pb)

        result = await service.get_breakdown(
            "site_1", "views_trend", "2026-01-01", "2026-01-01"
        )

        assert len(result) == 2
        assert result[0]["label"] == "prop_2"
        assert result[0]["value"] == 200
