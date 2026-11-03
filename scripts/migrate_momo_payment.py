"""PocketBase schema migration script for MoMo and external payment gateway tracking.

Adds external payment gateway tracking fields to the `payments` collection:
- gateway (text, required=False)
- partner_code (text, required=False)
- request_id (text, required=False, indexed)
- trans_id (text, required=False, indexed)
- pay_type (text, required=False)
- raw_payload (json, required=False)

Additive and idempotent. Supports --dry-run.
"""

import argparse
import asyncio
import copy
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings

COLLECTION_NAME = "payments"

NEW_FIELDS: list[dict[str, Any]] = [
    {"name": "gateway", "type": "text", "required": False},
    {"name": "partner_code", "type": "text", "required": False},
    {"name": "request_id", "type": "text", "required": False},
    {"name": "trans_id", "type": "text", "required": False},
    {"name": "pay_type", "type": "text", "required": False},
    {"name": "raw_payload", "type": "json", "required": False},
]

NEW_INDEXES: list[str] = [
    "CREATE INDEX idx_payments_request_id ON payments (request_id)",
    "CREATE INDEX idx_payments_trans_id ON payments (trans_id)",
]


def plan_migration(
    collection_data: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Compute the planned updated collection payload and diffs.

    Handles both PocketBase v0.23+ ("fields") and v0.22 ("schema") structures.
    """
    updated = copy.deepcopy(collection_data)

    field_container_key = "fields" if "fields" in updated else "schema"
    current_fields = updated.get(field_container_key, [])
    existing_field_names = {
        f["name"] for f in current_fields if isinstance(f, dict) and "name" in f
    }

    fields_to_add: list[dict[str, Any]] = []
    for field in NEW_FIELDS:
        if field["name"] not in existing_field_names:
            fields_to_add.append(field)
            current_fields.append(dict(field))

    updated[field_container_key] = current_fields

    current_indexes = updated.get("indexes", [])
    if not isinstance(current_indexes, list):
        current_indexes = []

    indexes_to_add: list[str] = []
    for idx in NEW_INDEXES:
        if idx not in current_indexes:
            indexes_to_add.append(idx)
            current_indexes.append(idx)

    updated["indexes"] = current_indexes

    return updated, fields_to_add, indexes_to_add


async def run_migration(
    pocketbase_url: str | None = None,
    admin_email: str | None = None,
    admin_password: str | None = None,
    dry_run: bool = False,
) -> None:
    settings = get_settings()

    base_url = (pocketbase_url or settings.pocketbase_url or "").rstrip("/")
    email = admin_email or settings.pocketbase_admin_email
    password = admin_password or settings.pocketbase_admin_password

    print("--- MoMo / Payment Gateway Migration ---")
    print(f"Target URL: {base_url}")
    print(f"Target Collection: {COLLECTION_NAME}")
    print(f"Dry Run Mode: {dry_run}")

    if dry_run and (not email or not password):
        print(
            "\n[Dry Run Info] Admin credentials not provided; printing planned schema changes based on defaults:"
        )
        print("Planned fields to ensure:")
        for f in NEW_FIELDS:
            print(f"  - {f['name']} (type: {f['type']}, required: {f['required']})")
        print("Planned indexes to ensure:")
        for idx in NEW_INDEXES:
            print(f"  - {idx}")
        print("\nDry run completed successfully (no remote changes made).")
        return

    if not email or not password:
        raise SystemExit(
            "POCKETBASE_ADMIN_EMAIL and POCKETBASE_ADMIN_PASSWORD must be configured in environment, config.yaml, or CLI flags."
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Authenticate as superuser / admin
        auth_url = f"{base_url}/api/collections/_superusers/auth-with-password"
        try:
            auth_resp = await client.post(
                auth_url,
                json={"identity": email, "password": password},
            )
            # PocketBase legacy fallback if _superusers endpoint returns 404
            if auth_resp.status_code == 404:
                auth_resp = await client.post(
                    f"{base_url}/api/admins/auth-with-password",
                    json={"identity": email, "password": password},
                )
            auth_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SystemExit(
                f"Failed to authenticate with PocketBase at {base_url}: {exc}"
            ) from exc

        token = auth_resp.json().get("token")
        headers = {"Authorization": token}

        # Fetch payments collection
        col_resp = await client.get(
            f"{base_url}/api/collections/{COLLECTION_NAME}",
            headers=headers,
        )
        if col_resp.status_code == 404:
            raise SystemExit(
                f"Error: Collection '{COLLECTION_NAME}' does not exist in PocketBase!"
            )
        col_resp.raise_for_status()

        col_data = col_resp.json()
        col_id = col_data.get("id", COLLECTION_NAME)

        updated_payload, fields_to_add, indexes_to_add = plan_migration(col_data)

        if not fields_to_add and not indexes_to_add:
            print(
                f"\nCollection '{COLLECTION_NAME}' is already up-to-date. No migration needed."
            )
            return

        print(f"\nChanges to apply to '{COLLECTION_NAME}':")
        if fields_to_add:
            print(f"  New Fields ({len(fields_to_add)}):")
            for f in fields_to_add:
                print(f"    + {f['name']} (type={f['type']}, required={f['required']})")
        else:
            print("  Fields: All fields already exist.")

        if indexes_to_add:
            print(f"  New Indexes ({len(indexes_to_add)}):")
            for idx in indexes_to_add:
                print(f"    + {idx}")
        else:
            print("  Indexes: All indexes already exist.")

        if dry_run:
            print("\n[Dry Run] No changes written to PocketBase.")
            return

        # Apply schema update
        patch_resp = await client.patch(
            f"{base_url}/api/collections/{col_id}",
            headers=headers,
            json=updated_payload,
        )
        patch_resp.raise_for_status()
        print(
            f"\nSuccessfully migrated '{COLLECTION_NAME}' collection schema in PocketBase!"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate PocketBase payments collection to include MoMo / external gateway fields."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration and print planned schema modifications without modifying live database.",
    )
    parser.add_argument(
        "--pocketbase-url",
        type=str,
        default=None,
        help="PocketBase base URL (overrides POCKETBASE_URL from settings).",
    )
    parser.add_argument(
        "--admin-email",
        type=str,
        default=None,
        help="PocketBase admin email (overrides POCKETBASE_ADMIN_EMAIL from settings).",
    )
    parser.add_argument(
        "--admin-password",
        type=str,
        default=None,
        help="PocketBase admin password (overrides POCKETBASE_ADMIN_PASSWORD from settings).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        run_migration(
            pocketbase_url=args.pocketbase_url,
            admin_email=args.admin_email,
            admin_password=args.admin_password,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
