from datetime import UTC, datetime

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient

logger = get_logger("analytics.aggregator")

COLLECTION = "analytics_daily_agg"
EVENT_COLLECTION = "analytics_events"


def _parse_user_agent(user_agent: str) -> tuple[str, str]:
    """Parse user agent string into (traffic_source, device_type)."""
    ua = user_agent.lower()

    # Device type
    if any(k in ua for k in ("mobile", "android", "iphone")):
        device_type = "mobile"
    elif any(k in ua for k in ("tablet", "ipad")):
        device_type = "tablet"
    else:
        device_type = "desktop"

    # Traffic source (simplified)
    if any(k in ua for k in ("google", "bing", "yahoo", "duckduckgo")):
        traffic_source = "search"
    elif any(
        k in ua for k in ("facebook", "twitter", "instagram", "linkedin", "tiktok")
    ):
        traffic_source = "social"
    else:
        traffic_source = "direct"

    return traffic_source, device_type


class AnalyticsAggregator:
    """Roll up raw analytics_events into daily aggregates."""

    def __init__(self, pb: PocketBaseClient, token: str | None = None) -> None:
        self._pb = pb
        self._token = token

    async def aggregate_daily(self, site_id: str, date: str) -> dict | None:
        """Query events for a day, compute aggregates, upsert to daily_agg."""
        try:
            # Fetch all events for this site and date
            filter_expr = f'site_id="{site_id}" && created_at>="{date}T00:00:00Z" && created_at<="{date}T23:59:59Z"'
            result = await self._pb.list_records(
                EVENT_COLLECTION, token=self._token, filter=filter_expr, per_page=500
            )
            events = result.get("items", [])

            if not events:
                return None

            # Compute aggregates
            agg = self._compute_aggregates(site_id, date, events)

            # Upsert site-level aggregate
            agg_id = f"{site_id}_{date}_site"
            agg["agg_id"] = agg_id
            await self._upsert(agg)

            # Per-property aggregates
            property_groups: dict[str, list] = {}
            for event in events:
                prop_id = event.get("property_id", "")
                if prop_id:
                    property_groups.setdefault(prop_id, []).append(event)

            for prop_id, prop_events in property_groups.items():
                prop_agg = self._compute_aggregates(
                    site_id, date, prop_events, property_id=prop_id
                )
                prop_agg_id = f"{site_id}_{date}_{prop_id}"
                prop_agg["agg_id"] = prop_agg_id
                prop_agg["property_id"] = prop_id
                await self._upsert(prop_agg)

            logger.info(
                "daily aggregation completed",
                extra={"site_id": site_id, "date": date, "events": len(events)},
            )
            return agg

        except Exception as e:
            logger.error(
                "daily aggregation failed",
                extra={"site_id": site_id, "date": date, "error": str(e)},
            )
            return None

    def _compute_aggregates(
        self,
        site_id: str,
        date: str,
        events: list[dict],
        property_id: str | None = None,
    ) -> dict:
        unique_visitors: set[str] = set()
        total_views = 0
        product_views = 0
        product_impressions = 0
        add_to_carts = 0
        purchases = 0
        revenue = 0.0
        search_count = 0
        search_queries: dict[str, int] = {}
        session_durations: list[float] = []
        session_pages: dict[str, int] = {}
        traffic_sources: dict[str, int] = {}
        device_types: dict[str, int] = {}

        for event in events:
            event_type = event.get("event_type", "")
            ip_hash = event.get("ip_hash", "")
            metadata = event.get("metadata") or {}
            session_id = event.get("session_id", "")
            user_agent = event.get("user_agent", "")

            if ip_hash:
                unique_visitors.add(ip_hash)

            # Parse traffic source and device type
            traffic_source, device_type = _parse_user_agent(user_agent)
            traffic_sources[traffic_source] = traffic_sources.get(traffic_source, 0) + 1
            device_types[device_type] = device_types.get(device_type, 0) + 1

            if event_type in ("page_view", "product_view"):
                total_views += 1
            if event_type == "product_view":
                product_views += 1
            if event_type == "product_impression":
                product_impressions += 1
            if event_type == "add_to_cart":
                add_to_carts += 1
            if event_type == "purchase":
                purchases += 1
                revenue += float(metadata.get("total", 0) or 0)
            if event_type == "search":
                search_count += 1
                query = metadata.get("query", "")
                if query:
                    search_queries[query] = search_queries.get(query, 0) + 1
            if event_type == "session_end":
                duration = metadata.get("duration_seconds", 0)
                if duration:
                    session_durations.append(float(duration))
            if event_type == "page_view" and session_id:
                session_pages[session_id] = session_pages.get(session_id, 0) + 1

        # Top search queries (top 10)
        top_queries = sorted(search_queries.items(), key=lambda x: x[1], reverse=True)[
            :10
        ]

        avg_session_duration = (
            sum(session_durations) / len(session_durations)
            if session_durations
            else None
        )
        pages_per_session = (
            sum(session_pages.values()) / len(session_pages) if session_pages else None
        )

        return {
            "date": date,
            "site_id": site_id,
            "property_id": property_id,
            "tenant_id": events[0].get("tenant_id", "") if events else "",
            "total_views": total_views,
            "unique_visitors": len(unique_visitors),
            "product_views": product_views,
            "product_impressions": product_impressions,
            "add_to_carts": add_to_carts,
            "purchases": purchases,
            "revenue": revenue,
            "search_count": search_count,
            "search_queries": [{"query": q, "count": c} for q, c in top_queries],
            "avg_session_duration": avg_session_duration,
            "pages_per_session": pages_per_session,
            "traffic_sources": traffic_sources,
            "device_types": device_types,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

    async def _upsert(self, agg: dict) -> None:
        """Upsert an aggregate record."""
        try:
            agg_id = agg.get("agg_id", "")
            existing = await self._pb.list_records(
                COLLECTION,
                filter=f'agg_id="{agg_id}"',
                per_page=1,
            )
            items = existing.get("items", [])

            if items:
                record_id = items[0]["id"]
                await self._pb.update_record(COLLECTION, record_id, agg)
            else:
                await self._pb.create_record(COLLECTION, agg)
        except Exception as e:
            logger.error(
                "analytics aggregate upsert failed",
                extra={"agg_id": agg.get("agg_id"), "error": str(e)},
            )
