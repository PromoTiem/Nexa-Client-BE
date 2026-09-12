"""Seed analytics events for Muot Spa site."""
import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta

import httpx

PB_URL = "http://127.0.0.1:8090"
SITE_ID = "muot-spa"
TENANT_ID = "gcotrfevn2m7an7"

# Muot Spa service property IDs
SPA_SERVICES = [
    ("svc_massage-co-ban", "Massage Thư Giãn Cơ Bản"),
    ("svc-massage-da-nong", "Massage Đá Nóng"),
    ("svc-massage-sau-mo", "Massage Sâu Mô"),
    ("svc-lieu-trinh-huong", "Liệu Trình Hương"),
    ("svc-cham-soc-da-mat", "Chăm Sóc Da Mặt Cao Cấp"),
    ("svc-tay-te-bao-chet", "Tẩy Tế Bào Chết Toàn Thân"),
    ("svc-ngam-thao-moc", "Tắm Ngâm Thảo Mộc"),
    ("svc-xong-hoi", "Xông Hơi Tinh Dầu"),
    ("svc-tri-lieu-da-dau", "Trị Liệu Da Đầu & Tóc"),
    ("svc-goi-da-chuyen-sau", "Gội Đầu Sinh Chuyên Sâu"),
    ("svc-massage-b-b-b", "Massage Cho Bà Bầu"),
    ("svc-cham-soc-mong-da", "Chăm Sóc Móng & Da Tay"),
]

SEARCH_QUERIES = [
    "massage", "facial", "spa", "đá nóng", "massage sâu mô",
    "chăm sóc da", "xông hơi", "liệu trình hương", "gội đầu",
    "tẩy tế bào", "massage thư giãn", "da đầu", "tóc",
]

IP_HASHES = [f"ip_{uuid.uuid4().hex[:8]}" for _ in range(40)]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14) Chrome/120.0",
    "Mozilla/5.0 (iPad; CPU OS 17_0) Safari/605.1.15",
]


def random_dt(days_ago: int) -> str:
    """Random datetime within a day, days_ago from now."""
    now = datetime.now(UTC)
    day = now - timedelta(days=days_ago)
    hour = random.randint(7, 22)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return day.replace(hour=hour, minute=minute, second=second).isoformat()


def random_date(days_ago: int) -> str:
    now = datetime.now(UTC)
    return (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def make_event(event_type: str, days_ago: int, **kwargs) -> dict:
    prop = random.choice(SPA_SERVICES) if event_type in ("product_view", "add_to_cart", "purchase") else None
    property_id = kwargs.get("property_id", prop[0] if prop else "")
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "event_type": event_type,
        "site_id": SITE_ID,
        "property_id": property_id,
        "tenant_id": TENANT_ID,
        "session_id": f"sess_{uuid.uuid4().hex[:8]}",
        "metadata": kwargs.get("metadata", {}),
        "ip_hash": random.choice(IP_HASHES),
        "user_agent": random.choice(USER_AGENTS),
        "created_at": random_dt(days_ago),
    }


def generate_events() -> list[dict]:
    events = []
    for day in range(30, -1, -1):
        # Weekend boost
        day_dt = datetime.now(UTC) - timedelta(days=day)
        is_weekend = day_dt.weekday() >= 5
        base = 1.5 if is_weekend else 1.0

        # Page views (10-25 per day)
        for _ in range(int(random.randint(10, 25) * base)):
            events.append(make_event("page_view", day))

        # Product views (8-18 per day)
        for _ in range(int(random.randint(8, 18) * base)):
            events.append(make_event("product_view", day))

        # Add to cart (2-6 per day) — booking intent
        for _ in range(int(random.randint(2, 6) * base)):
            prop = random.choice(SPA_SERVICES)
            events.append(make_event("add_to_cart", day, property_id=prop[0]))

        # Purchases (1-3 per day) — completed bookings
        for _ in range(int(random.randint(1, 3) * base)):
            prop = random.choice(SPA_SERVICES)
            price = random.choice([85, 95, 120, 150, 200, 375, 700])
            events.append(make_event("purchase", day, property_id=prop[0],
                                     metadata={"total": price, "currency": "USD"}))

        # Searches (1-5 per day)
        for _ in range(random.randint(1, 5)):
            query = random.choice(SEARCH_QUERIES)
            events.append(make_event("search", day, metadata={"query": query}))

        # Sessions (3-8 per day)
        for _ in range(random.randint(3, 8)):
            duration = random.randint(30, 1800)
            events.append(make_event("session_end", day,
                                     metadata={"duration_seconds": duration}))

    return events


async def seed():
    events = generate_events()
    print(f"Generated {len(events)} events")

    # Get admin token
    async with httpx.AsyncClient() as client:
        auth_resp = await client.post(
            f"{PB_URL}/api/collections/_superusers/auth-with-password",
            json={"identity": "admin@gmail.com", "password": "admin123456"},
        )
        token = auth_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Insert events in chunks of 100
        accepted = 0
        for i in range(0, len(events), 100):
            chunk = events[i:i+100]
            for event in chunk:
                try:
                    resp = await client.post(
                        f"{PB_URL}/api/collections/analytics_events/records",
                        json=event,
                        headers=headers,
                    )
                    if resp.status_code in (200, 201):
                        accepted += 1
                    else:
                        print(f"  Event create failed: {resp.status_code} {resp.text[:200]}")
                except Exception as e:
                    print(f"  Event create error: {e}")
            print(f"  Inserted chunk {i//100 + 1}, total accepted: {accepted}")

        print(f"\nSeeding complete: {accepted}/{len(events)} events accepted")


if __name__ == "__main__":
    asyncio.run(seed())
