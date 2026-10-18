"""Create the transactional PocketBase collections used by orders/bookings.

The migration is additive and idempotent. It never deletes or rewrites an
existing collection. Run with the normal PocketBase admin settings loaded.
"""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings


COLLECTIONS = {
    "orders": {
        "fields": [
            ("order_id", "text", True), ("site_id", "text", True),
            ("customer_name", "text", False), ("customer_email", "email", False),
            ("customer_phone", "text", False), ("status", "select", True),
            ("total", "number", True), ("currency", "text", True),
            ("notes", "text", False), ("metadata", "json", False),
            ("deleted_at", "date", False),
        ],
        "indexes": ["CREATE UNIQUE INDEX idx_orders_order_id ON orders (order_id)", "CREATE INDEX idx_orders_site_id ON orders (site_id)", "CREATE INDEX idx_orders_status ON orders (status)"],
    },
    "order_items": {
        "fields": [
            ("item_id", "text", True), ("order_id", "text", True), ("property_id", "text", True),
            ("quantity", "number", True), ("unit_price", "number", True), ("total_price", "number", True),
            ("variation", "json", False), ("metadata", "json", False),
        ],
        "indexes": ["CREATE UNIQUE INDEX idx_order_items_item_id ON order_items (item_id)", "CREATE INDEX idx_order_items_order_id ON order_items (order_id)", "CREATE INDEX idx_order_items_property_id ON order_items (property_id)"],
    },
    "payments": {
        "fields": [
            ("payment_id", "text", True), ("order_id", "text", True), ("method", "text", True),
            ("amount", "number", True), ("currency", "text", True), ("status", "text", True),
            ("transaction_ref", "text", False), ("notes", "text", False), ("metadata", "json", False),
        ],
        "indexes": ["CREATE UNIQUE INDEX idx_payments_payment_id ON payments (payment_id)", "CREATE INDEX idx_payments_order_id ON payments (order_id)", "CREATE INDEX idx_payments_status ON payments (status)"],
    },
    "bookings": {
        "fields": [
            ("booking_id", "text", True), ("site_id", "text", True), ("property_id", "text", True),
            ("customer_name", "text", True), ("customer_email", "email", True), ("customer_phone", "text", False),
            ("date", "date", True), ("start_time", "text", True), ("end_time", "text", True),
            ("status", "text", True), ("notes", "text", False), ("fields", "json", False),
            ("metadata", "json", False), ("deleted_at", "date", False),
        ],
        "indexes": ["CREATE UNIQUE INDEX idx_bookings_booking_id ON bookings (booking_id)", "CREATE INDEX idx_bookings_site_id ON bookings (site_id)", "CREATE INDEX idx_bookings_property_id ON bookings (property_id)", "CREATE INDEX idx_bookings_date ON bookings (date)", "CREATE INDEX idx_bookings_status ON bookings (status)"],
    },
    "availability": {
        "fields": [
            ("availability_id", "text", True), ("site_id", "text", True), ("property_id", "text", True),
            ("day_of_week", "text", True), ("start_time", "text", True), ("end_time", "text", True),
            ("max_bookings", "number", False), ("is_active", "bool", True), ("metadata", "json", False),
        ],
        "indexes": ["CREATE UNIQUE INDEX idx_availability_availability_id ON availability (availability_id)", "CREATE INDEX idx_availability_site_property ON availability (site_id, property_id)", "CREATE INDEX idx_availability_day ON availability (day_of_week)"],
    },
}


def schema_for(fields: list[tuple[str, str, bool]]) -> list[dict]:
    select_values = [
        "pending", "paid", "fulfilled", "cancelled", "confirmed",
        "completed", "failed", "refunded", "other",
    ]
    result = []
    for name, type_name, required in fields:
        field = {"name": name, "type": type_name, "required": required}
        if type_name == "select":
            field.update({"maxSelect": 1, "values": select_values})
        result.append(field)
    return result


async def main() -> None:
    settings = get_settings()
    if not settings.pocketbase_admin_email or not settings.pocketbase_admin_password:
        raise SystemExit("POCKETBASE_ADMIN_EMAIL and POCKETBASE_ADMIN_PASSWORD are required")
    base = settings.pocketbase_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        auth = await client.post(f"{base}/api/collections/_superusers/auth-with-password", json={"identity": settings.pocketbase_admin_email, "password": settings.pocketbase_admin_password})
        auth.raise_for_status()
        headers = {"Authorization": auth.json()["token"]}
        for name, definition in COLLECTIONS.items():
            response = await client.get(f"{base}/api/collections/{name}", headers=headers)
            if response.status_code == 200:
                print(f"{name}: exists")
                continue
            payload = {"name": name, "type": "base", "fields": schema_for(definition["fields"]), "indexes": definition["indexes"], "listRule": "@request.auth.id != ''", "viewRule": "@request.auth.id != ''"}
            created = await client.post(f"{base}/api/collections", headers=headers, json=payload)
            created.raise_for_status()
            print(f"{name}: created")


if __name__ == "__main__":
    asyncio.run(main())
