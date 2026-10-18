"""Backfill structured bookings from legacy booking_submission properties.

Records without the required structured fields are reported and left intact.
The migration is idempotent through the legacy_property_id metadata marker.
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings
from app.infrastructure.pocketbase.client import PocketBaseClient


def values_from_fields(fields: list[dict]) -> dict:
    return {field.get("key"): field.get("value") for field in fields if field.get("key")}


async def main() -> None:
    settings = get_settings()
    if not settings.pocketbase_admin_email or not settings.pocketbase_admin_password:
        raise SystemExit("POCKETBASE_ADMIN_EMAIL and POCKETBASE_ADMIN_PASSWORD are required")
    pb = PocketBaseClient(settings.pocketbase_url, static_token=None)
    auth = await pb.auth_admin(settings.pocketbase_admin_email, settings.pocketbase_admin_password)
    pb = PocketBaseClient(settings.pocketbase_url, static_token=auth["token"])
    page = 1
    converted = skipped = existing = 0
    while True:
        result = await pb.list_records("properties", token=auth["token"], filter='type="booking_submission" && deleted_at=""', page=page, per_page=100)
        items = result.get("items", [])
        for submission in items:
            service_id = (submission.get("metadata") or {}).get("service_id")
            values = values_from_fields(submission.get("fields", []))
            required = {"customer_name": values.get("customer_name") or values.get("name"), "customer_email": values.get("customer_email") or values.get("email"), "date": values.get("date"), "start_time": values.get("start_time"), "end_time": values.get("end_time")}
            if not service_id or any(value in (None, "") for value in required.values()):
                skipped += 1
                print(f"SKIP {submission.get('property_id')}: incomplete structured booking fields")
                continue
            marker = f'legacy_property_id="{submission.get("property_id")}"'
            found = await pb.list_records("bookings", token=auth["token"], filter=marker, per_page=1)
            if found.get("items"):
                existing += 1
                continue
            await pb.create_record("bookings", {"booking_id": f"booking_{uuid.uuid4().hex}", "site_id": submission["site_id"], "property_id": service_id, **required, "customer_phone": values.get("customer_phone") or values.get("phone"), "status": "pending", "fields": submission.get("fields", []), "metadata": {"source": "backfill", "legacy_property_id": submission.get("property_id")}, "deleted_at": ""}, token=auth["token"])
            converted += 1
        if page >= result.get("totalPages", page):
            break
        page += 1
    print(f"converted={converted} skipped={skipped} existing={existing}")


if __name__ == "__main__":
    asyncio.run(main())
