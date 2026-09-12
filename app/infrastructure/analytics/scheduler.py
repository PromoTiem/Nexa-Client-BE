import asyncio
from datetime import UTC, datetime, timedelta

from app.infrastructure.analytics.aggregator import AnalyticsAggregator
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient

logger = get_logger("analytics.scheduler")

COLLECTION_SITES = "sites"
COLLECTION_EVENTS = "analytics_events"


class DailyAggregationScheduler:
    """Background scheduler that runs daily aggregation for all active sites."""

    def __init__(
        self,
        pb: PocketBaseClient,
        aggregation_hour: int = 2,
        retention_days: int | None = None,
    ) -> None:
        self._pb = pb
        self._aggregation_hour = aggregation_hour
        self._retention_days = retention_days
        self._aggregator = AnalyticsAggregator(pb)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "daily aggregation scheduler started",
            extra={
                "aggregation_hour": self._aggregation_hour,
                "retention_days": self._retention_days,
            },
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("daily aggregation scheduler stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                now = datetime.now(UTC)
                target = now.replace(
                    hour=self._aggregation_hour, minute=0, second=0, microsecond=0
                )
                if target <= now:
                    target += timedelta(days=1)
                wait_seconds = (target - now).total_seconds()
                logger.info(
                    "next aggregation scheduled",
                    extra={
                        "target": target.isoformat(),
                        "wait_seconds": int(wait_seconds),
                    },
                )
                await asyncio.sleep(wait_seconds)
                await self._run_aggregation()
                if self._retention_days is not None:
                    await self._run_cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "daily aggregation scheduler error", extra={"error": str(e)}
                )
                await asyncio.sleep(60)

    async def _run_aggregation(self) -> None:
        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info("starting daily aggregation", extra={"date": yesterday})

        site_ids = await self._list_active_site_ids()
        if not site_ids:
            logger.info("no active sites found for aggregation")
            return

        aggregated = 0
        for site_id in site_ids:
            result = await self._aggregator.aggregate_daily(site_id, yesterday)
            if result:
                aggregated += 1

        logger.info(
            "daily aggregation completed",
            extra={
                "date": yesterday,
                "total_sites": len(site_ids),
                "aggregated": aggregated,
            },
        )

    async def _run_cleanup(self) -> None:
        if self._retention_days is None:
            return
        cutoff = (datetime.now(UTC) - timedelta(days=self._retention_days)).strftime(
            "%Y-%m-%dT00:00:00Z"
        )
        logger.info(
            "running retention cleanup",
            extra={"cutoff": cutoff, "retention_days": self._retention_days},
        )

        try:
            page = 1
            total_deleted = 0
            while True:
                result = await self._pb.list_records(
                    COLLECTION_EVENTS,
                    filter=f'created_at<"{cutoff}"',
                    page=page,
                    per_page=500,
                )
                items = result.get("items", [])
                total = result.get("totalItems", 0)

                for item in items:
                    try:
                        await self._pb.delete_record(COLLECTION_EVENTS, item["id"])
                        total_deleted += 1
                    except Exception as e:
                        logger.warning(
                            "failed to delete old event",
                            extra={"id": item.get("id"), "error": str(e)},
                        )

                if len(items) < 500 or total_deleted >= total:
                    break
                page += 1

            logger.info("retention cleanup completed", extra={"deleted": total_deleted})
        except Exception as e:
            logger.error("retention cleanup failed", extra={"error": str(e)})

    async def _list_active_site_ids(self) -> list[str]:
        """Fetch all active site IDs from PocketBase."""
        try:
            all_ids: list[str] = []
            page = 1
            while True:
                result = await self._pb.list_records(
                    COLLECTION_SITES,
                    filter='status="active"',
                    page=page,
                    per_page=500,
                )
                items = result.get("items", [])
                for item in items:
                    sid = item.get("site_id") or item.get("id", "")
                    if sid:
                        all_ids.append(sid)
                total = result.get("totalItems", 0)
                if len(all_ids) >= total or len(items) < 500:
                    break
                page += 1
            return all_ids
        except Exception as e:
            logger.error("failed to list active sites", extra={"error": str(e)})
            return []
