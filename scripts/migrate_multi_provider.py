#!/usr/bin/env python3
"""Add provider_id field to availability and bookings collections in PocketBase.

Idempotent migration: adds provider_id (text, optional) if missing.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings

TARGET_COLLECTIONS = ["availability", "bookings"]
FIELD_NAME = "provider_id"
FIELD_DEF = {
    "name": FIELD_NAME,
    "type": "text",
    "required": False,
    "presentable": False,
    "primaryKey": False,
    "system": False,
    "hidden": False,
    "min": 0,
    "max": 0,
    "pattern": "",
    "autogeneratePattern": "",
}


async def migrate(token: str | None = None) -> int:
    settings = get_settings()
    base = settings.pocketbase_url.rstrip("/")

    async with httpx.AsyncClient(timeout=30.0) as client:
        if token:
            admin_token = token
        elif settings.pocketbase_admin_email and settings.pocketbase_admin_password:
            auth = await client.post(
                f"{base}/api/collections/_superusers/auth-with-password",
                json={
                    "identity": settings.pocketbase_admin_email,
                    "password": settings.pocketbase_admin_password,
                },
            )
            auth.raise_for_status()
            admin_token = auth.json()["token"]
        else:
            print(
                "ERROR: provide --token or set POCKETBASE_ADMIN_EMAIL and POCKETBASE_ADMIN_PASSWORD",
                file=sys.stderr,
            )
            return 1

        headers = {"Authorization": admin_token}

        for col_name in TARGET_COLLECTIONS:
            resp = await client.get(
                f"{base}/api/collections/{col_name}", headers=headers
            )
            if resp.status_code != 200:
                print(
                    f"WARNING: collection '{col_name}' not found: {resp.status_code}",
                    file=sys.stderr,
                )
                continue

            col = resp.json()
            fields = col.get("fields")
            schema = col.get("schema")

            if fields is not None:
                existing_names = {f.get("name") for f in fields}
                if FIELD_NAME in existing_names:
                    print(f"OK: '{col_name}.{FIELD_NAME}' already exists")
                    continue
                fields.append(FIELD_DEF)
                patch_payload = {"fields": fields}
            elif schema is not None:
                existing_names = {f.get("name") for f in schema}
                if FIELD_NAME in existing_names:
                    print(f"OK: '{col_name}.{FIELD_NAME}' already exists")
                    continue
                schema.append(
                    {
                        "name": FIELD_NAME,
                        "type": "text",
                        "required": False,
                    }
                )
                patch_payload = {"schema": schema}
            else:
                patch_payload = {"fields": [FIELD_DEF]}

            upd = await client.patch(
                f"{base}/api/collections/{col_name}",
                headers=headers,
                json=patch_payload,
            )
            if upd.status_code >= 400:
                print(
                    f"ERROR: failed updating '{col_name}': {upd.status_code} {upd.text}",
                    file=sys.stderr,
                )
                return 1
            print(f"OK: added '{FIELD_NAME}' to '{col_name}'")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate multi-provider fields to availability and bookings"
    )
    parser.add_argument("--token", help="Superuser JWT (overrides config credentials)")
    args = parser.parse_args()
    return asyncio.run(migrate(token=args.token))


if __name__ == "__main__":
    sys.exit(main())
