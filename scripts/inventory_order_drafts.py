"""Read-only hidden-order inventory for explicit operator reconciliation.

Output contains record IDs/counts, not customer data. Never auto-publishes or
deletes an order. Retry keyed drafts through the normal authenticated API.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.services.transactional_service import (
    TransactionalService,
    filter_value,
)
from app.config import get_settings
from app.infrastructure.pocketbase.client import PocketBaseClient


def classify(order, items, payments):
    state = (order.get("metadata") or {}).get("_creation", {})
    if payments:
        category = "payment_present_manual_review"
    elif state.get("state") == "building" and state.get("fingerprint"):
        category = "keyed_creation_retry_required"
    elif state.get("state") == "complete":
        category = "deleted_completed_order_do_not_restore"
    else:
        category = "legacy_unkeyed_manual_review"
    return {
        "record_id": order["id"],
        "order_id": order["order_id"],
        "category": category,
        "item_count": len(items),
        "payment_count": len(payments),
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-id", required=True)
    args = parser.parse_args()
    settings = get_settings()
    pb = PocketBaseClient(settings.pocketbase_url)
    auth = await pb.auth_admin(
        settings.pocketbase_admin_email, settings.pocketbase_admin_password
    )
    token = auth["token"]
    service = TransactionalService()
    rows = await service._all_records(
        pb, token, "orders", f'site_id={filter_value(args.site_id)} && deleted_at!=""'
    )
    report = []
    for order in rows:
        items = await service._order_children(
            pb, token, "order_items", order["order_id"]
        )
        payments = await service._order_children(
            pb, token, "payments", order["order_id"]
        )
        report.append(classify(order, items, payments))
    print(
        json.dumps(
            {"mode": "read_only", "site_id": args.site_id, "orders": report}, indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
