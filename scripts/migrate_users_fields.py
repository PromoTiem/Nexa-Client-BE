#!/usr/bin/env python3
"""Add multi-tenant fields to PocketBase `users` collection (idempotent).

Adds `tenant_id`, `role`, `status`, `phone`, `metadata`, `last_login`
and updates collection rules for tenant-scoped admin access.

Reads connection + superuser creds from app.config (config.yaml / env), so:
    PYTHONPATH=. python scripts/migrate_users_fields.py

Or pass a superuser JWT directly:
    PYTHONPATH=. python scripts/migrate_users_fields.py --token <JWT>

Safe to re-run: existing fields are left untouched.
"""
import argparse
import sys

import httpx

from app.config import get_settings

COLLECTION = "users"

# Fields to ensure. Shapes match PocketBase v0.22+ field schema.
NEW_FIELDS = [
    {
        "name": "tenant_id", "type": "text", "required": False,
        "system": False, "hidden": False, "min": 0, "max": 0,
        "pattern": "", "autogeneratePattern": "",
        "presentable": False, "primaryKey": False,
    },
    {
        "name": "role", "type": "select", "required": False,
        "system": False, "hidden": False, "presentable": False,
        "values": ["owner", "admin", "member", "guest"], "maxSelect": 1,
    },
    {
        "name": "status", "type": "select", "required": False,
        "system": False, "hidden": False, "presentable": False,
        "values": ["active", "inactive", "pending"], "maxSelect": 1,
    },
    {
        "name": "phone", "type": "text", "required": False,
        "system": False, "hidden": False, "min": 0, "max": 0,
        "pattern": "", "autogeneratePattern": "",
        "presentable": False, "primaryKey": False,
    },
    {
        "name": "metadata", "type": "json", "required": False,
        "system": False, "hidden": False, "presentable": False,
        "maxSize": 2000000,
    },
    {
        "name": "last_login", "type": "date", "required": False,
        "system": False, "hidden": False, "presentable": False,
        "min": "", "max": "",
    },
    {
        "name": "name", "type": "text", "required": False,
        "system": False, "hidden": False, "min": 0, "max": 0,
        "pattern": "", "autogeneratePattern": "",
        "presentable": False, "primaryKey": False,
    },
    {
        "name": "avatar", "type": "file", "required": False,
        "system": False, "hidden": False, "presentable": False,
        "maxSelect": 1, "maxSize": 0,
        "mimeTypes": ["image/jpeg", "image/png", "image/svg+xml", "image/webp", "image/gif"],
    },
    {
        "name": "created", "type": "autodate", "required": False,
        "system": False, "hidden": False, "presentable": False,
        "onCreate": True, "onUpdate": False,
    },
    {
        "name": "updated", "type": "autodate", "required": False,
        "system": False, "hidden": False, "presentable": False,
        "onCreate": True, "onUpdate": True,
    },
]

# Updated rules for tenant-scoped admin access
COLLECTION_RULES = {
    "listRule": "@request.auth.role = 'owner' || @request.auth.role = 'admin' || @request.auth.is_superuser = true",
    "viewRule": "id = @request.auth.id || @request.auth.role = 'owner' || @request.auth.role = 'admin' || @request.auth.is_superuser = true",
    "createRule": "@request.auth.role = 'owner' || @request.auth.role = 'admin' || @request.auth.is_superuser = true",
    "updateRule": "id = @request.auth.id || @request.auth.role = 'owner' || @request.auth.role = 'admin' || @request.auth.is_superuser = true",
    "deleteRule": "@request.auth.role = 'owner' || @request.auth.is_superuser = true",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate users collection")
    parser.add_argument("--token", help="Superuser JWT (overrides config creds)")
    args = parser.parse_args()

    s = get_settings()
    base = s.pocketbase_url.rstrip("/")

    # Auth: explicit token > config admin creds
    if args.token:
        token = args.token
    elif s.pocketbase_admin_email and s.pocketbase_admin_password:
        with httpx.Client(timeout=30.0) as c:
            auth = c.post(
                f"{base}/api/collections/_superusers/auth-with-password",
                json={"identity": s.pocketbase_admin_email,
                      "password": s.pocketbase_admin_password},
            )
            auth.raise_for_status()
            token = auth.json()["token"]
    else:
        print("ERROR: provide --token or configure pocketbase_admin_email/password",
              file=sys.stderr)
        return 1

    headers = {"Authorization": token}

    with httpx.Client(timeout=30.0) as c:
        col = c.get(f"{base}/api/collections/{COLLECTION}", headers=headers)
        col.raise_for_status()
        col = col.json()

        fields = col.get("fields", [])
        existing = {f["name"] for f in fields}

        to_add = [f for f in NEW_FIELDS if f["name"] not in existing]
        if to_add:
            fields.extend(to_add)

        # Check if rules need updating
        rules_changed = any(
            col.get(k) != v for k, v in COLLECTION_RULES.items()
        )

        if not to_add and not rules_changed:
            print(f"OK: '{COLLECTION}' schema and rules are up to date")
            return 0

        payload: dict = {"fields": fields}
        if rules_changed:
            payload.update(COLLECTION_RULES)

        upd = c.patch(
            f"{base}/api/collections/{COLLECTION}",
            headers=headers, json=payload,
        )
        if upd.status_code >= 400:
            print(f"ERROR: PATCH failed {upd.status_code}: {upd.text}", file=sys.stderr)
            return 1

        msg = []
        if to_add:
            msg.append(f"added {len(to_add)} field(s): {', '.join(f['name'] for f in to_add)}")
        if rules_changed:
            msg.append("updated collection rules")
        print(f"OK: '{COLLECTION}' migration applied ({'; '.join(msg)})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
