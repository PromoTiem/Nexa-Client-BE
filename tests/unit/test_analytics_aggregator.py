from unittest.mock import AsyncMock

import pytest

from app.infrastructure.analytics.aggregator import AnalyticsAggregator, _parse_user_agent


class TestParseUserAgent:
    def test_desktop_browser(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        source, device = _parse_user_agent(ua)
        assert device == "desktop"
        assert source == "direct"

    def test_mobile_device(self):
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"
        source, device = _parse_user_agent(ua)
        assert device == "mobile"

    def test_tablet_device(self):
        ua = "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X)"
        source, device = _parse_user_agent(ua)
        assert device == "tablet"

    def test_google_bot(self):
        ua = "Mozilla/5.0 (compatible; Googlebot/2.1)"
        source, device = _parse_user_agent(ua)
        assert source == "search"

    def test_facebook_referral(self):
        ua = "Mozilla/5.0 (compatible; Facebookbot/1.0)"
        source, device = _parse_user_agent(ua)
        assert source == "social"

    def test_empty_user_agent(self):
        source, device = _parse_user_agent("")
        assert device == "desktop"
        assert source == "direct"


class TestComputeAggregates:
    def setup_method(self):
        self.aggregator = AnalyticsAggregator(AsyncMock())

    def test_empty_events(self):
        agg = self.aggregator._compute_aggregates("site_1", "2026-01-01", [])
        assert agg["total_views"] == 0
        assert agg["unique_visitors"] == 0
        assert agg["revenue"] == 0.0

    def test_page_views(self):
        events = [
            {"event_type": "page_view", "ip_hash": "a", "user_agent": "", "metadata": {}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "page_view", "ip_hash": "b", "user_agent": "", "metadata": {}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "product_view", "ip_hash": "a", "user_agent": "", "metadata": {}, "session_id": "s1", "tenant_id": "t1"},
        ]
        agg = self.aggregator._compute_aggregates("site_1", "2026-01-01", events)
        assert agg["total_views"] == 3
        assert agg["product_views"] == 1
        assert agg["unique_visitors"] == 2

    def test_purchases_and_revenue(self):
        events = [
            {"event_type": "purchase", "ip_hash": "a", "user_agent": "", "metadata": {"total": 99.99}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "purchase", "ip_hash": "b", "user_agent": "", "metadata": {"total": 49.50}, "session_id": "s2", "tenant_id": "t1"},
        ]
        agg = self.aggregator._compute_aggregates("site_1", "2026-01-01", events)
        assert agg["purchases"] == 2
        assert agg["revenue"] == 149.49

    def test_search_queries(self):
        events = [
            {"event_type": "search", "ip_hash": "a", "user_agent": "", "metadata": {"query": "shoes"}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "search", "ip_hash": "a", "user_agent": "", "metadata": {"query": "shoes"}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "search", "ip_hash": "b", "user_agent": "", "metadata": {"query": "hats"}, "session_id": "s2", "tenant_id": "t1"},
        ]
        agg = self.aggregator._compute_aggregates("site_1", "2026-01-01", events)
        assert agg["search_count"] == 3
        queries = {q["query"]: q["count"] for q in agg["search_queries"]}
        assert queries["shoes"] == 2
        assert queries["hats"] == 1

    def test_traffic_sources_and_device_types(self):
        events = [
            {"event_type": "page_view", "ip_hash": "a", "user_agent": "Mozilla/5.0 (iPhone)", "metadata": {}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "page_view", "ip_hash": "b", "user_agent": "Mozilla/5.0 (Windows)", "metadata": {}, "session_id": "s2", "tenant_id": "t1"},
        ]
        agg = self.aggregator._compute_aggregates("site_1", "2026-01-01", events)
        assert agg["device_types"]["mobile"] == 1
        assert agg["device_types"]["desktop"] == 1

    def test_session_duration_and_pages(self):
        events = [
            {"event_type": "session_end", "ip_hash": "a", "user_agent": "", "metadata": {"duration_seconds": 120}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "session_end", "ip_hash": "b", "user_agent": "", "metadata": {"duration_seconds": 60}, "session_id": "s2", "tenant_id": "t1"},
            {"event_type": "page_view", "ip_hash": "a", "user_agent": "", "metadata": {}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "page_view", "ip_hash": "a", "user_agent": "", "metadata": {}, "session_id": "s1", "tenant_id": "t1"},
            {"event_type": "page_view", "ip_hash": "b", "user_agent": "", "metadata": {}, "session_id": "s2", "tenant_id": "t1"},
        ]
        agg = self.aggregator._compute_aggregates("site_1", "2026-01-01", events)
        assert agg["avg_session_duration"] == 90.0
        assert agg["pages_per_session"] == 1.5


class TestAnalyticsAggregatorAggregateDaily:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_events(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(return_value={"items": [], "totalItems": 0})
        aggregator = AnalyticsAggregator(pb)

        result = await aggregator.aggregate_daily("site_1", "2026-01-01")

        assert result is None

    @pytest.mark.asyncio
    async def test_aggregates_events_and_upserts(self):
        pb = AsyncMock()
        events = [
            {"event_type": "page_view", "ip_hash": "a", "user_agent": "", "metadata": {}, "session_id": "s1", "tenant_id": "t1", "property_id": ""},
        ]
        pb.list_records = AsyncMock(return_value={"items": events, "totalItems": 1})
        pb.create_record = AsyncMock(return_value={"id": "rec_1"})
        aggregator = AnalyticsAggregator(pb)

        result = await aggregator.aggregate_daily("site_1", "2026-01-01")

        assert result is not None
        assert result["total_views"] == 1
        assert result["agg_id"] == "site_1_2026-01-01_site"

    @pytest.mark.asyncio
    async def test_creates_per_property_aggregates(self):
        pb = AsyncMock()
        events = [
            {"event_type": "page_view", "ip_hash": "a", "user_agent": "", "metadata": {}, "session_id": "s1", "tenant_id": "t1", "property_id": "prop_1"},
            {"event_type": "page_view", "ip_hash": "a", "user_agent": "", "metadata": {}, "session_id": "s1", "tenant_id": "t1", "property_id": "prop_2"},
        ]
        call_count = 0

        async def list_records_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call: fetch events
            if call_count == 1:
                return {"items": events, "totalItems": 2}
            # Subsequent calls: upsert checks (no existing aggregates)
            return {"items": [], "totalItems": 0}

        pb.list_records = AsyncMock(side_effect=list_records_side_effect)
        pb.create_record = AsyncMock(return_value={"id": "rec_1"})
        aggregator = AnalyticsAggregator(pb)

        result = await aggregator.aggregate_daily("site_1", "2026-01-01")

        assert result is not None
        # list_records: 1 for events + 3 for upsert checks (site + 2 properties)
        assert pb.list_records.call_count == 4
        # create_record: site-level + 2 property-level
        assert pb.create_record.call_count == 3
