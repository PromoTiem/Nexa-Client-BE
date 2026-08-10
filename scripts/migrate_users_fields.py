#!/usr/bin/env python3
"""Add multi-tenant fields to PocketBase `users` collection (idempotent).

Adds `tenant_id`, `role`, `status`, `phone`, `metadata`, `last_login`,
`is_superuser` and updates collection rules for tenant-scoped admin access.

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
    {
        "name": "is_superuser", "type": "bool", "required": False,
        "system": False, "hidden": False, "presentable": False,
    },
]

# Simplified rules: just require authentication, app layer handles RBAC
COLLECTION_RULES = {
    "listRule": "@request.auth.id != \"\"",
    "viewRule": "id = @request.auth.id || @request.auth.id != \"\"",
    "createRule": "@request.auth.id != \"\"",
    "updateRule": "id = @request.auth.id || @request.auth.id != \"\"",
    "deleteRule": "@request.auth.id != \"\"",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate users collection")
    parser.add_argument("--token", help="Superuser JWT (overrides config creds)")
    parser.add_argument("--backfill-roles", action="store_true",
                        help="Backfill users missing role with 'member'")
    parser.add_argument("--migrate-superusers", action="store_true",
                        help="Migrate _superusers into users collection with is_superuser=true")
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

        if not to_add and not rules_changed and not args.backfill_roles and not args.migrate_superusers:
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

        # Backfill users missing role
        if args.backfill_roles or args.migrate_superusers:
            users = c.get(
                f"{base}/api/collections/{COLLECTION}/records",
                headers=headers,
                params={"perPage": 500, "page": 1},
            )
            users.raise_for_status()
            users_data = users.json()

            for user in users_data.get("items", []):
                updates = {}

                if args.backfill_roles and not user.get("role"):
                    updates["role"] = "member"

                if args.migrate_superusers and user.get("email") in (
                    s.pocketbase_admin_email or ""
                ):
                    updates["is_superuser"] = True
                    if not user.get("role"):
                        updates["role"] = "owner"

                if updates:
                    patch_resp = c.patch(
                        f"{base}/api/collections/{COLLECTION}/records/{user['id']}",
                        headers=headers, json=updates,
                    )
                    if patch_resp.status_code >= 400:
                        print(f"WARNING: failed to update user {user['id']}: {patch_resp.text}",
                              file=sys.stderr)
                    else:
                        msg.append(f"updated user {user['id']}")

        # Migrate _superusers into users collection
        if args.migrate_superusers:
            try:
                superusers = c.get(
                    f"{base}/api/collections/_superusers/records",
                    headers=headers,
                    params={"perPage": 500, "page": 1},
                )
                if superusers.status_code == 200:
                    superusers_data = superusers.json()
                    for su in superusers_data.get("items", []):
                        # Check if user with this email already exists
                        existing_user = c.get(
                            f"{base}/api/collections/{COLLECTION}/records",
                            headers=headers,
                            params={
                                "filter": f'email="{su["email"]}"',
                                "perPage": 1,
                            },
                        )
                        existing_user.raise_for_status()
                        existing_data = existing_user.json()

                        if not existing_data.get("items"):
                            # Create user from superuser
                            import secrets
                            temp_password = secrets.token_urlsafe(16)
                            create_resp = c.post(
                                f"{base}/api/collections/{COLLECTION}/records",
                                headers=headers,
                                json={
                                    "email": su["email"],
                                    "password": temp_password,
                                    "passwordConfirm": temp_password,
                                    "name": su.get("name", ""),
                                    "role": "owner",
                                    "is_superuser": True,
                                    "status": "active",
                                },
                            )
                            if create_resp.status_code >= 400:
                                print(f"WARNING: failed to create user for {su['email']}: {create_resp.text}",
                                      file=sys.stderr)
                            else:
                                msg.append(f"created user for superuser {su['email']}")
                        else:
                            # Update existing user
                            existing_id = existing_data["items"][0]["id"]
                            patch_resp = c.patch(
                                f"{base}/api/collections/{COLLECTION}/records/{existing_id}",
                                headers=headers,
                                json={"is_superuser": True, "role": "owner"},
                            )
                            if patch_resp.status_code >= 400:
                                print(f"WARNING: failed to update superuser {su['email']}: {patch_resp.text}",
                                      file=sys.stderr)
                            else:
                                msg.append(f"marked {su['email']} as superuser")
            except Exception as e:
                print(f"WARNING: _superusers migration skipped: {e}", file=sys.stderr)

        print(f"OK: '{COLLECTION}' migration applied ({'; '.join(msg)})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
