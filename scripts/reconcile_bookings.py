"""Site-scoped legacy reconciliation; dry-run unless --apply is supplied."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.services.legacy_booking_service import convert_submission
from app.application.services.transactional_service import filter_value
from app.config import get_settings
from app.infrastructure.operation_lock import operation_lock
from app.infrastructure.pocketbase.client import PocketBaseClient


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    pb = PocketBaseClient(settings.pocketbase_url)
    auth = await pb.auth_admin(
        settings.pocketbase_admin_email, settings.pocketbase_admin_password
    )
    token = auth["token"]
    counts = {
        "converted": 0,
        "existing": 0,
        "incomplete": 0,
        "would_convert": 0,
        "failed": 0,
    }
    page = 1
    while True:
        result = await pb.list_records(
            "properties",
            token=token,
            filter=f'site_id={filter_value(args.site_id)} && type="booking_submission" && deleted_at=""',
            sort="id",
            page=page,
            per_page=100,
        )
        for row in result.get("items", []):
            try:
                async with operation_lock("site:" + args.site_id):
                    current = await pb.find_record_by_id(
                        "properties", row["id"], token=token
                    )
                    if current.get("site_id") != args.site_id:
                        raise ValueError("Source changed site")
                    outcome = await convert_submission(
                        pb, token, current, source="backfill", apply=args.apply
                    )
                counts[outcome] += 1
            except Exception as exc:
                counts["failed"] += 1
                print(
                    json.dumps(
                        {
                            "source_id": row.get("property_id"),
                            "error_type": type(exc).__name__,
                        }
                    )
                )
        if page >= result.get("totalPages", 1):
            break
        page += 1
    print(json.dumps({"apply": args.apply, "counts": counts}))
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
