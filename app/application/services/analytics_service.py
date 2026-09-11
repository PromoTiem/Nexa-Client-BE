from datetime import UTC, datetime, timedelta

from app.infrastructure.analytics.aggregator import AnalyticsAggregator
from app.infrastructure.analytics.collector import AnalyticsCollector
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient

logger = get_logger("analytics.service")

COLLECTION_AGG = "analytics_daily_agg"


class AnalyticsService:
    """Business logic for analytics event tracking and dashboard queries."""

    def __init__(
        self,
        collector: AnalyticsCollector,
        aggregator: AnalyticsAggregator,
        pb: PocketBaseClient,
        token: str | None = None,
    ) -> None:
        self._collector = collector
        self._aggregator = aggregator
        self._pb = pb
        self._token = token

    # --- Event Tracking ---

    async def track_event(
        self,
        event_type: str,
        site_id: str,
        *,
        property_id: str | None = None,
        tenant_id: str = "",
        session_id: str = "",
        metadata: dict | None = None,
        user_agent: str = "",
        timestamp: str | None = None,
    ) -> str:
        return await self._collector.record_event(
            event_type=event_type,
            site_id=site_id,
            property_id=property_id,
            tenant_id=tenant_id,
            session_id=session_id,
            metadata=metadata,
            user_agent=user_agent,
            timestamp=timestamp,
        )

    async def track_batch(self, events: list[dict]) -> dict:
        accepted = 0
        rejected = 0
        for event in events:
            try:
                await self._collector.record_event(**event)
                accepted += 1
            except Exception as e:
                rejected += 1
                logger.warning("event track failed", extra={"error": str(e)})
        return {"accepted": accepted, "rejected": rejected, "errors": []}

    async def flush(self) -> dict:
        return await self._collector.flush()

    async def aggregate_daily(self, site_id: str, date: str | None = None) -> dict | None:
        if date is None:
            date = datetime.now(UTC).strftime("%Y-%m-%d")
        return await self._aggregator.aggregate_daily(site_id, date)

    # --- Dashboard Queries ---

    async def get_kpis(
        self,
        site_id: str,
        start: str,
        end: str,
        *,
        property_id: str | None = None,
    ) -> dict:
        """Sum daily aggregates across a date range into KPI totals."""
        aggs = await self._query_aggregates(site_id, start, end, property_id=property_id)
        if not aggs:
            return {
                "total_views": 0, "unique_visitors": 0, "product_views": 0,
                "bookings": 0, "orders": 0, "revenue": 0.0,
                "conversion_rate": 0.0, "avg_order_value": 0.0, "search_count": 0,
            }

        total_views = sum(a.get("total_views", 0) or 0 for a in aggs)
        unique_visitors = sum(a.get("unique_visitors", 0) or 0 for a in aggs)
        product_views = sum(a.get("product_views", 0) or 0 for a in aggs)
        bookings = sum(a.get("add_to_carts", 0) or 0 for a in aggs)
        orders = sum(a.get("purchases", 0) or 0 for a in aggs)
        revenue = sum(a.get("revenue", 0) or 0 for a in aggs)
        search_count = sum(a.get("search_count", 0) or 0 for a in aggs)

        conversion_rate = (orders / total_views * 100) if total_views else 0.0
        avg_order_value = (revenue / orders) if orders else 0.0

        return {
            "total_views": total_views,
            "unique_visitors": unique_visitors,
            "product_views": product_views,
            "bookings": bookings,
            "orders": orders,
            "revenue": round(revenue, 2),
            "conversion_rate": round(conversion_rate, 2),
            "avg_order_value": round(avg_order_value, 2),
            "search_count": search_count,
        }

    async def get_kpis_change(
        self,
        site_id: str,
        period: str,
    ) -> dict[str, float]:
        """Compute percentage change vs previous period for each KPI."""
        start, end = self._date_range(period)
        prev_start, prev_end = self._previous_period_range(start, end)

        current = await self.get_kpis(site_id, start, end)
        previous = await self.get_kpis(site_id, prev_start, prev_end)

        changes: dict[str, float] = {}
        for key in current:
            curr_val = current[key]
            prev_val = previous[key]
            if prev_val and prev_val != 0:
                changes[key] = round((curr_val - prev_val) / prev_val * 100, 1)
            else:
                changes[key] = 0.0
        return changes

    async def get_trend(
        self,
        site_id: str,
        metric: str,
        start: str,
        end: str,
        *,
        property_id: str | None = None,
    ) -> list[dict]:
        """Return time-series data for a single metric from daily aggregates."""
        aggs = await self._query_aggregates(site_id, start, end, property_id=property_id)
        field = _METRIC_TO_FIELD.get(metric)
        if not field:
            return []

        data = []
        for a in sorted(aggs, key=lambda x: x.get("date", "")):
            data.append({"date": a["date"], "value": a.get(field, 0) or 0})
        return data

    async def get_breakdown(
        self,
        site_id: str,
        metric: str,
        start: str,
        end: str,
    ) -> list[dict]:
        """Return per-property breakdown (for pie/bar charts)."""
        aggs = await self._query_aggregates(site_id, start, end, include_properties=True)

        # Group by property_id
        by_prop: dict[str, int | float] = {}
        for a in aggs:
            prop_id = a.get("property_id") or ""
            if not prop_id:
                continue
            field = _METRIC_TO_FIELD.get(metric)
            val = a.get(field, 0) or 0 if field else 0
            by_prop[prop_id] = by_prop.get(prop_id, 0) + val

        items = []
        for prop_id, value in sorted(by_prop.items(), key=lambda x: x[1], reverse=True):
            items.append({"label": prop_id, "value": value, "property_id": prop_id})
        return items

    async def get_top_properties(
        self,
        site_id: str,
        metric: str,
        start: str,
        end: str,
        *,
        limit: int = 10,
    ) -> list[dict]:
        """Return top properties ranked by a metric."""
        aggs = await self._query_aggregates(site_id, start, end, include_properties=True)

        # Aggregate per property
        by_prop: dict[str, dict] = {}
        for a in aggs:
            prop_id = a.get("property_id") or ""
            if not prop_id:
                continue
            if prop_id not in by_prop:
                by_prop[prop_id] = {
                    "property_id": prop_id,
                    "views": 0,
                    "bookings": 0,
                    "revenue": 0.0,
                }
            by_prop[prop_id]["views"] += a.get("total_views", 0) or 0
            by_prop[prop_id]["bookings"] += a.get("add_to_carts", 0) or 0
            by_prop[prop_id]["revenue"] += a.get("revenue", 0) or 0

        # Sort by requested metric
        sort_key = _TOP_SORT_KEY.get(metric, "views")
        ranked = sorted(by_prop.values(), key=lambda x: x.get(sort_key, 0), reverse=True)
        return ranked[:limit]

    # --- Date Utilities ---

    def _date_range(self, period: str) -> tuple[str, str]:
        now = datetime.now(UTC)
        end = now.strftime("%Y-%m-%d")
        if period == "7d":
            start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        elif period == "90d":
            start = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        elif period == "1y":
            start = (now - timedelta(days=365)).strftime("%Y-%m-%d")
        elif period == "all":
            start = "2020-01-01"
        else:  # 30d default
            start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        return start, end

    def _previous_period_range(self, start: str, end: str) -> tuple[str, str]:
        """Compute the previous period range of equal length before `start`."""
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        length = (end_dt - start_dt).days
        prev_end = start_dt - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length)
        return prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d")

    # --- Internal Queries ---

    async def _query_aggregates(
        self,
        site_id: str,
        start: str,
        end: str,
        *,
        property_id: str | None = None,
        include_properties: bool = False,
    ) -> list[dict]:
        """Query analytics_daily_agg for a site + date range."""
        parts = [f'site_id="{site_id}"']
        parts.append(f'date>="{start}"')
        parts.append(f'date<="{end}"')

        if property_id:
            parts.append(f'property_id="{property_id}"')
        elif not include_properties:
            # Site-level aggregates only (agg_id ends with _site)
            parts.append('property_id=""')

        filter_expr = " && ".join(parts)

        logger.debug(
            "querying aggregates",
            extra={"site_id": site_id, "filter": filter_expr, "has_token": self._token is not None},
        )

        result = await self._pb.list_records(
            COLLECTION_AGG,
            token=self._token,
            filter=filter_expr,
            per_page=500,
            sort="date",
        )
        return result.get("items", [])


# --- Metric Mappings ---

_METRIC_TO_FIELD: dict[str, str] = {
    "views_trend": "total_views",
    "unique_visitors_trend": "unique_visitors",
    "product_views_trend": "product_views",
    "bookings_trend": "add_to_carts",
    "orders_trend": "purchases",
    "revenue_trend": "revenue",
    "search_trend": "search_count",
}

_TOP_SORT_KEY: dict[str, str] = {
    "views": "views",
    "bookings": "bookings",
    "revenue": "revenue",
}
