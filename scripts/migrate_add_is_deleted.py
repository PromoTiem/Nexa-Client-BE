"""Migration: Add is_deleted field to the users collection.

Usage:
    python scripts/migrate_add_is_deleted.py

Requires POCKETBASE_URL, POCKETBASE_ADMIN_EMAIL, and POCKETBASE_ADMIN_PASSWORD
environment variables (or values in config.yaml).
"""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings


COLLECTION = "users"
FIELD_NAME = "is_deleted"


async def migrate() -> None:
    settings = get_settings()
    base_url = settings.pocketbase_url.rstrip("/")

    if not settings.pocketbase_admin_email or not settings.pocketbase_admin_password:
        print("ERROR: POCKETBASE_ADMIN_EMAIL and POCKETBASE_ADMIN_PASSWORD must be set")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Authenticate as admin
        print("Authenticating as admin...")
        auth_resp = await client.post(
            f"{base_url}/api/admins/auth-with-password",
            json={
                "identity": settings.pocketbase_admin_email,
                "password": settings.pocketbase_admin_password,
            },
        )
        if auth_resp.status_code != 200:
            print(f"ERROR: Admin auth failed: {auth_resp.status_code} {auth_resp.text}")
            sys.exit(1)

        admin_token = auth_resp.json()["token"]
        headers = {"Authorization": admin_token}
        print("Admin authenticated.")

        # 2. Get current collection schema
        print(f"Fetching '{COLLECTION}' collection schema...")
        col_resp = await client.get(
            f"{base_url}/api/collections/{COLLECTION}",
            headers=headers,
        )
        if col_resp.status_code != 200:
            print(f"ERROR: Failed to fetch collection: {col_resp.status_code} {col_resp.text}")
            sys.exit(1)

        collection = col_resp.json()
        schema = collection.get("schema", [])

        # 3. Check if field already exists
        existing_fields = [f["name"] for f in schema]
        if FIELD_NAME in existing_fields:
            print(f"Field '{FIELD_NAME}' already exists. Skipping.")
            return

        # 4. Add the new field
        schema.append({
            "name": FIELD_NAME,
            "type": "bool",
            "required": False,
            "options": {
                "values": [True, False],
            },
        })

        # 5. Update collection schema
        print(f"Adding '{FIELD_NAME}' field to '{COLLECTION}' collection...")
        update_resp = await client.patch(
            f"{base_url}/api/collections/{COLLECTION}",
            headers=headers,
            json={"schema": schema},
        )
        if update_resp.status_code != 200:
            print(f"ERROR: Failed to update collection: {update_resp.status_code} {update_resp.text}")
            sys.exit(1)

        print(f"Successfully added '{FIELD_NAME}' field to '{COLLECTION}' collection.")

        # 6. Optionally backfill existing soft-deleted users
        print("Backfilling existing inactive users with is_deleted=True...")
        page = 1
        total_updated = 0
        while True:
            list_resp = await client.get(
                f"{base_url}/api/collections/{COLLECTION}/records",
                headers=headers,
                params={
                    "filter": 'status="inactive"',
                    "page": page,
                    "perPage": 100,
                },
            )
            if list_resp.status_code != 200:
                print(f"WARNING: Failed to list records: {list_resp.status_code}")
                break

            data = list_resp.json()
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                if not item.get(FIELD_NAME, False):
                    await client.patch(
                        f"{base_url}/api/collections/{COLLECTION}/records/{item['id']}",
                        headers=headers,
                        json={FIELD_NAME: True},
                    )
                    total_updated += 1

            if page >= data.get("totalPages", 1):
                break
            page += 1

        print(f"Backfill complete. Updated {total_updated} records.")
        print("Migration finished.")


if __name__ == "__main__":
    asyncio.run(migrate())
