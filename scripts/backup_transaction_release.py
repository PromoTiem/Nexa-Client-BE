"""Create a native PocketBase backup and a private source/schema rollback bundle."""

import asyncio
import json
import os
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import httpx


async def main():
    # Run with PYTHONPATH pointing to the current deployed checkout.
    from app.config import get_settings

    os.umask(0o077)
    root = Path.home() / ".local/state/nexa-rollouts"
    root.mkdir(parents=True, exist_ok=True)
    target = root / (
        datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-transactions-preflight"
    )
    target.mkdir(mode=0o700)
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.pocketbase_url, timeout=180
    ) as client:
        auth = await client.post(
            "/api/collections/_superusers/auth-with-password",
            json={
                "identity": settings.pocketbase_admin_email,
                "password": settings.pocketbase_admin_password,
            },
        )
        auth.raise_for_status()
        client.headers["Authorization"] = auth.json()["token"]
        key = target.name + ".zip"
        response = await client.post("/api/backups", json={"name": key})
        response.raise_for_status()
        listed = await client.get("/api/backups")
        listed.raise_for_status()
        entries = listed.json()
        if not any(
            entry.get("key") == key and entry.get("size", 0) > 0 for entry in entries
        ):
            raise RuntimeError("Native backup not present or empty")
        schemas = []
        for name in (
            "users",
            "sites",
            "tenants",
            "properties",
            "orders",
            "order_items",
            "payments",
            "bookings",
            "availability",
        ):
            response = await client.get("/api/collections/" + name)
            response.raise_for_status()
            schemas.append(response.json())
        (target / "schemas.json").write_text(json.dumps(schemas, indent=2))
        (target / "backup.json").write_text(
            json.dumps({"native_backup": key, "production_changed": False}, indent=2)
        )
    checkout = Path.home() / "Nexa-Client-BE"
    with tarfile.open(target / "source.tar.gz", "w:gz") as archive:
        for name in (
            "app",
            "scripts",
            "tests",
            "config.yaml",
            "run.py",
            "requirements.txt",
            "requirements-dev.txt",
        ):
            path = checkout / name
            if path.exists():
                archive.add(path, arcname=name)
    (target / "source-head.txt").write_text(
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True)
    )
    hooks = Path.home() / "pb"
    with tarfile.open(target / "hooks-migrations.tar.gz", "w:gz") as archive:
        for name in ("pb_hooks", "pb_migrations"):
            archive.add(hooks / name, arcname=name)
    print("Private rollback bundle:", target)
    print("Native PocketBase backup:", key)


if __name__ == "__main__":
    asyncio.run(main())
