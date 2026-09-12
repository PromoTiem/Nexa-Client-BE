"""Aggregate seeded analytics events into daily rollups for Muot Spa with full metadata."""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx

PB_URL = "http://127.0.0.1:8090"
SITE_ID = "muot-spa"
TENANT_ID = "gcotrfevn2m7an7"


def parse_user_agent(ua: str) -> tuple[str, str]:
    ua_lower = ua.lower()
    if any(k in ua_lower for k in ("mobile", "android", "iphone")):
        device = "mobile"
    elif any(k in ua_lower for k in ("tablet", "ipad")):
        device = "tablet"
    else:
        device = "desktop"
    if any(k in ua_lower for k in ("google", "bing", "yahoo", "duckduckgo")):
        source = "search"
    elif any(k in ua_lower for k in ("facebook", "twitter", "instagram", "linkedin", "tiktok")):
        source = "social"
    else:
        source = "direct"
    return source, device


def compute_aggregates(events: list[dict], site_id: str, date: str, prop_id: str = "") -> dict:
    unique_visitors = set()
    total_views = 0
    product_views = 0
    add_to_carts = 0
    purchases = 0
    revenue = 0.0
    search_count = 0
    search_queries = {}
    session_durations = []
    session_pages = {}
    traffic_sources = {}
    device_types = {}

    for e in events:
        et = e.get("event_type", "")
        ip = e.get("ip_hash", "")
        meta = e.get("metadata") or {}
        sid = e.get("session_id", "")
        ua = e.get("user_agent", "")

        if ip:
            unique_visitors.add(ip)

        source, device = parse_user_agent(ua)
        traffic_sources[source] = traffic_sources.get(source, 0) + 1
        device_types[device] = device_types.get(device, 0) + 1

        if et in ("page_view", "product_view"):
            total_views += 1
        if et == "product_view":
            product_views += 1
        if et == "add_to_cart":
            add_to_carts += 1
        if et == "purchase":
            purchases += 1
            revenue += float(meta.get("total", 0) or 0)
        if et == "search":
            search_count += 1
            q = meta.get("query", "")
            if q:
                search_queries[q] = search_queries.get(q, 0) + 1
        if et == "session_end":
            dur = meta.get("duration_seconds", 0)
            if dur:
                session_durations.append(float(dur))
        if et == "page_view" and sid:
            session_pages[sid] = session_pages.get(sid, 0) + 1

    top_queries = sorted(search_queries.items(), key=lambda x: x[1], reverse=True)[:10]
    avg_session_duration = round(sum(session_durations) / len(session_durations), 2) if session_durations else None
    pages_per_session = round(sum(session_pages.values()) / len(session_pages), 2) if session_pages else None

    return {
        "date": date,
        "site_id": site_id,
        "property_id": prop_id,
        "tenant_id": TENANT_ID,
        "total_views": total_views,
        "unique_visitors": len(unique_visitors),
        "product_views": product_views,
        "product_impressions": 0,
        "add_to_carts": add_to_carts,
        "purchases": purchases,
        "revenue": revenue,
        "search_count": search_count,
        "search_queries": [{"query": q, "count": c} for q, c in top_queries],
        "avg_session_duration": avg_session_duration,
        "pages_per_session": pages_per_session,
        "traffic_sources": traffic_sources,
        "device_types": device_types,
    }


async def upsert_agg(client: httpx.AsyncClient, token: str, agg: dict) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    agg_id = agg["agg_id"]
    resp = await client.get(
        f"{PB_URL}/api/collections/analytics_daily_agg/records",
        params={"filter": f'agg_id="{agg_id}"', "per_page": 1},
        headers=headers,
    )
    existing = resp.json().get("items", [])
    if existing:
        await client.patch(
            f"{PB_URL}/api/collections/analytics_daily_agg/records/{existing[0]['id']}",
            json=agg,
            headers=headers,
        )
    else:
        await client.post(
            f"{PB_URL}/api/collections/analytics_daily_agg/records",
            json=agg,
            headers=headers,
        )


async def aggregate_day(client: httpx.AsyncClient, token: str, date: str) -> dict | None:
    headers = {"Authorization": f"Bearer {token}"}
    filter_expr = f'site_id="{SITE_ID}" && created_at>="{date}T00:00:00Z" && created_at<="{date}T23:59:59Z"'
    resp = await client.get(
        f"{PB_URL}/api/collections/analytics_events/records",
        params={"filter": filter_expr, "per_page": 500},
        headers=headers,
    )
    events = resp.json().get("items", [])
    if not events:
        return None

    # Site-level aggregate
    site_agg = compute_aggregates(events, SITE_ID, date)
    site_agg["agg_id"] = f"{SITE_ID}_{date}_site"
    await upsert_agg(client, token, site_agg)

    # Per-property aggregates
    prop_groups: dict[str, list] = {}
    for e in events:
        pid = e.get("property_id", "")
        if pid:
            prop_groups.setdefault(pid, []).append(e)

    for pid, prop_events in prop_groups.items():
        prop_agg = compute_aggregates(prop_events, SITE_ID, date, prop_id=pid)
        prop_agg["agg_id"] = f"{SITE_ID}_{date}_{pid}"
        await upsert_agg(client, token, prop_agg)

    return {
        "date": date,
        "events": len(events),
        "views": site_agg["total_views"],
        "purchases": site_agg["purchases"],
        "revenue": site_agg["revenue"],
        "traffic": site_agg["traffic_sources"],
        "devices": site_agg["device_types"],
        "properties": len(prop_groups),
    }


async def main():
    async with httpx.AsyncClient() as client:
        auth = await client.post(
            f"{PB_URL}/api/collections/_superusers/auth-with-password",
            json={"identity": "admin@gmail.com", "password": "admin123456"},
        )
        token = auth.json()["token"]

        now = datetime.now(UTC)
        print(f"Aggregating {SITE_ID} for last 31 days...\n")

        for day in range(31, -1, -1):
            date = (now - timedelta(days=day)).strftime("%Y-%m-%d")
            result = await aggregate_day(client, token, date)
            if result:
                print(
                    f"  {date}: {result['events']:3d} events, "
                    f"{result['views']:3d} views, "
                    f"{result['purchases']} purchases, "
                    f"${result['revenue']:.0f}, "
                    f"props={result['properties']}, "
                    f"traffic={result['traffic']}, "
                    f"devices={result['devices']}"
                )

        agg_resp = await client.get(
            f"{PB_URL}/api/collections/analytics_daily_agg/records",
            params={"per_page": 1, "filter": f'site_id="{SITE_ID}"'},
            headers={"Authorization": f"Bearer {token}"},
        )
        total_agg = agg_resp.json().get("totalItems", 0)
        print(f"\nDone! {total_agg} daily aggregates created.")


if __name__ == "__main__":
    asyncio.run(main())
