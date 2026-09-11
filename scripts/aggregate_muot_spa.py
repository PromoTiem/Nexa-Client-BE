"""Aggregate seeded analytics events into daily rollups for Muot Spa."""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx

PB_URL = "http://127.0.0.1:8090"
SITE_ID = "muot-spa"
TENANT_ID = "gcotrfevn2m7an7"


async def aggregate_day(client: httpx.AsyncClient, token: str, date: str) -> dict | None:
    headers = {"Authorization": f"Bearer {token}"}

    # Query events for this day
    filter_expr = f'site_id="{SITE_ID}" && created_at>="{date}T00:00:00Z" && created_at<="{date}T23:59:59Z"'
    resp = await client.get(
        f"{PB_URL}/api/collections/analytics_events/records",
        params={"filter": filter_expr, "per_page": 500},
        headers=headers,
    )
    events = resp.json().get("items", [])
    if not events:
        return None

    # Compute aggregates
    unique_visitors = set()
    total_views = 0
    product_views = 0
    add_to_carts = 0
    purchases = 0
    revenue = 0.0
    search_count = 0
    search_queries = {}

    for e in events:
        et = e.get("event_type", "")
        ip = e.get("ip_hash", "")
        meta = e.get("metadata") or {}

        if ip:
            unique_visitors.add(ip)
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

    top_queries = sorted(search_queries.items(), key=lambda x: x[1], reverse=True)[:10]

    agg = {
        "agg_id": f"{SITE_ID}_{date}_site",
        "date": date,
        "site_id": SITE_ID,
        "property_id": "",
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
        "avg_session_duration": None,
        "pages_per_session": None,
    }

    # Upsert
    existing_resp = await client.get(
        f"{PB_URL}/api/collections/analytics_daily_agg/records",
        params={"filter": f'agg_id="{agg["agg_id"]}"', "per_page": 1},
        headers=headers,
    )
    existing = existing_resp.json().get("items", [])

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

    return {
        "date": date,
        "events": len(events),
        "views": total_views,
        "visitors": len(unique_visitors),
        "purchases": purchases,
        "revenue": revenue,
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
                print(f"  {date}: {result['events']:3d} events, {result['views']:3d} views, {result['purchases']} purchases, ${result['revenue']:.0f}")

        # Verify
        agg_resp = await client.get(
            f"{PB_URL}/api/collections/analytics_daily_agg/records",
            params={"per_page": 1, "filter": f'site_id="{SITE_ID}"'},
            headers={"Authorization": f"Bearer {token}"},
        )
        total_agg = agg_resp.json().get("totalItems", 0)
        print(f"\nDone! {total_agg} daily aggregates created.")


if __name__ == "__main__":
    asyncio.run(main())
