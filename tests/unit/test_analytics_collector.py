from unittest.mock import AsyncMock

import pytest

from app.infrastructure.analytics.collector import AnalyticsCollector


class TestAnalyticsCollectorRecordEvent:
    @pytest.mark.asyncio
    async def test_record_event_returns_event_id(self):
        pb = AsyncMock()
        pb.create_record = AsyncMock(return_value={"id": "rec_1"})
        collector = AnalyticsCollector(pb, buffer_size=100, flush_interval=60)

        event_id = await collector.record_event(
            event_type="page_view",
            site_id="site_1",
            tenant_id="tenant_1",
            session_id="sess_1",
        )

        assert event_id.startswith("evt_")
        assert len(event_id) == 16  # "evt_" + 12 hex chars

    @pytest.mark.asyncio
    async def test_record_event_buffers_without_flushing(self):
        pb = AsyncMock()
        pb.create_record = AsyncMock()
        collector = AnalyticsCollector(pb, buffer_size=10, flush_interval=60)

        await collector.record_event(event_type="page_view", site_id="s1")
        await collector.record_event(event_type="page_view", site_id="s1")

        assert len(collector._buffer) == 2
        pb.create_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_event_flushes_when_buffer_full(self):
        pb = AsyncMock()
        pb.create_record = AsyncMock(return_value={"id": "rec_1"})
        collector = AnalyticsCollector(pb, buffer_size=3, flush_interval=60)

        for _ in range(3):
            await collector.record_event(event_type="page_view", site_id="s1")

        assert len(collector._buffer) == 0
        assert pb.create_record.call_count == 3

    @pytest.mark.asyncio
    async def test_record_event_stores_all_fields(self):
        pb = AsyncMock()
        pb.create_record = AsyncMock(return_value={"id": "rec_1"})
        collector = AnalyticsCollector(pb, buffer_size=100, flush_interval=60)

        await collector.record_event(
            event_type="product_view",
            site_id="site_1",
            property_id="prop_1",
            tenant_id="tenant_1",
            session_id="sess_1",
            metadata={"key": "value"},
            ip_hash="abc123",
            user_agent="Mozilla/5.0",
            timestamp="2026-01-01T00:00:00Z",
        )

        event = collector._buffer[0]
        assert event["event_type"] == "product_view"
        assert event["site_id"] == "site_1"
        assert event["property_id"] == "prop_1"
        assert event["tenant_id"] == "tenant_1"
        assert event["session_id"] == "sess_1"
        assert event["metadata"] == {"key": "value"}
        assert event["ip_hash"] == "abc123"
        assert event["user_agent"] == "Mozilla/5.0"
        assert event["created_at"] == "2026-01-01T00:00:00Z"


class TestAnalyticsCollectorFlush:
    @pytest.mark.asyncio
    async def test_flush_returns_zeros_when_empty(self):
        pb = AsyncMock()
        collector = AnalyticsCollector(pb)

        result = await collector.flush()

        assert result == {"accepted": 0, "rejected": 0}

    @pytest.mark.asyncio
    async def test_flush_sends_events_to_pocketbase(self):
        pb = AsyncMock()
        pb.create_record = AsyncMock(return_value={"id": "rec_1"})
        collector = AnalyticsCollector(pb)

        await collector.record_event(event_type="page_view", site_id="s1")
        await collector.record_event(event_type="purchase", site_id="s1")

        result = await collector.flush()

        assert result["accepted"] == 2
        assert result["rejected"] == 0
        assert pb.create_record.call_count == 2

    @pytest.mark.asyncio
    async def test_flush_handles_partial_failure_across_chunks(self):
        pb = AsyncMock()
        call_count = 0

        async def side_effect(collection, data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("PB error")
            return {"id": f"rec_{call_count}"}

        pb.create_record = AsyncMock(side_effect=side_effect)
        # Use buffer_size=1 so each event triggers a separate flush
        collector = AnalyticsCollector(pb, buffer_size=1)

        # Record 3 events, each will be flushed immediately
        await collector.record_event(event_type="page_view", site_id="s1")  # fails
        await collector.record_event(event_type="page_view", site_id="s1")  # succeeds
        await collector.record_event(event_type="page_view", site_id="s1")  # succeeds

        # The buffer is empty since each event was flushed immediately
        assert len(collector._buffer) == 0


class TestAnalyticsCollectorLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_flush_task(self):
        pb = AsyncMock()
        collector = AnalyticsCollector(pb, flush_interval=3600)

        await collector.start()
        assert collector._flush_task is not None
        assert not collector._flush_task.done()

        await collector.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task_and_flushes(self):
        pb = AsyncMock()
        pb.create_record = AsyncMock(return_value={"id": "rec_1"})
        collector = AnalyticsCollector(pb, flush_interval=3600)

        await collector.start()
        await collector.record_event(event_type="page_view", site_id="s1")
        await collector.stop()

        assert collector._flush_task.cancelled()
        assert len(collector._buffer) == 0
        assert pb.create_record.call_count == 1
