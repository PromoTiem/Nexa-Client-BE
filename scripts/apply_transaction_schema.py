"""Apply reviewed additive transaction schema changes, retaining a rollback snapshot."""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from transaction_schema_candidate import COLLECTIONS, candidate


async def main():
    from app.config import get_settings

    os.umask(0o077)
    target = Path(sys.argv[1])
    if not target.is_dir() or (target / "schema-before-apply.json").exists():
        raise RuntimeError(
            "Use an existing private backup directory without an apply snapshot"
        )
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.pocketbase_url, timeout=60
    ) as client:
        response = await client.post(
            "/api/collections/_superusers/auth-with-password",
            json={
                "identity": settings.pocketbase_admin_email,
                "password": settings.pocketbase_admin_password,
            },
        )
        response.raise_for_status()
        client.headers["Authorization"] = response.json()["token"]
        originals = []
        for name in COLLECTIONS:
            response = await client.get("/api/collections/" + name)
            response.raise_for_status()
            originals.append(response.json())
        (target / "schema-before-apply.json").write_text(
            json.dumps(originals, indent=2)
        )
        applied = []
        try:
            for schema in originals:
                response = await client.patch(
                    "/api/collections/" + schema["id"], json=candidate(schema)
                )
                response.raise_for_status()
                applied.append(schema)
                print(schema["name"], "schema applied; direct writes locked")
        except Exception:
            for schema in reversed(applied):
                response = await client.patch(
                    "/api/collections/" + schema["id"], json=schema
                )
                response.raise_for_status()
            raise
        (target / "schema-applied.json").write_text(
            json.dumps([candidate(schema) for schema in originals], indent=2)
        )


if __name__ == "__main__":
    asyncio.run(main())
