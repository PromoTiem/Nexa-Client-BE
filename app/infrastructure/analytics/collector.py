import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient

logger = get_logger("analytics.collector")

COLLECTION = "analytics_events"


class AnalyticsCollector:
    """In-memory buffer that flushes events to PocketBase in batches."""

    def __init__(
        self,
        pb: PocketBaseClient,
        buffer_size: int = 100,
        flush_interval: int = 5,
    ) -> None:
        self._pb = pb
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval
        self._buffer: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the periodic flush task."""
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(
            "analytics collector started",
            extra={"buffer_size": self._buffer_size, "flush_interval": self._flush_interval},
        )

    async def stop(self) -> None:
        """Stop the flush task and flush remaining events."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()
        logger.info("analytics collector stopped")

    async def record_event(
        self,
        event_type: str,
        site_id: str,
        *,
        property_id: str | None = None,
        tenant_id: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
        ip_hash: str = "",
        user_agent: str = "",
        timestamp: str | None = None,
    ) -> str:
        """Buffer an event. Returns the event_id."""
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()

        event = {
            "event_id": event_id,
            "event_type": event_type,
            "site_id": site_id,
            "property_id": property_id or "",
            "tenant_id": tenant_id,
            "session_id": session_id,
            "metadata": metadata or {},
            "ip_hash": ip_hash,
            "user_agent": user_agent,
            "created_at": timestamp or now,
        }

        async with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= self._buffer_size:
                await self._flush_unlocked()

        return event_id

    async def flush(self) -> dict[str, int]:
        """Flush all buffered events to PocketBase."""
        async with self._lock:
            return await self._flush_unlocked()

    async def _flush_unlocked(self) -> dict[str, int]:
        if not self._buffer:
            return {"accepted": 0, "rejected": 0}

        events = list(self._buffer)
        self._buffer.clear()

        accepted = 0
        rejected = 0

        # Create in chunks
        for i in range(0, len(events), 100):
            chunk = events[i : i + 100]
            try:
                for event in chunk:
                    await self._pb.create_record(COLLECTION, event)
                accepted += len(chunk)
            except Exception as e:
                rejected += len(chunk)
                logger.error(
                    "analytics batch create failed",
                    extra={"error": str(e), "chunk_size": len(chunk)},
                )

        logger.debug(
            "analytics flush completed",
            extra={"accepted": accepted, "rejected": rejected},
        )
        return {"accepted": accepted, "rejected": rejected}

    async def _periodic_flush(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("analytics periodic flush error", extra={"error": str(e)})
