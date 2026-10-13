from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.application.services.bucket_resolver import sanitize_bucket_name
from app.infrastructure.logging import get_logger
from app.infrastructure.operation_lock import operation_lock
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value
from app.infrastructure.storage.client import StorageClient

logger = get_logger("site_lifecycle")


async def create_site_record(
    pb: PocketBaseClient,
    storage: StorageClient,
    data: dict[str, Any],
    token: str,
    user_id: str,
    base_domain: str,
) -> dict[str, Any]:
    site_id = data["site_id"]
    # The route validates the public ID syntax. Storage and Pages names are
    # normalized separately; the existence/reservation checks below prevent
    # normalized-name collisions without rejecting existing public ID formats.
    bucket = sanitize_bucket_name(site_id)
    if await storage.bucket_exists(bucket):
        raise HTTPException(status_code=409, detail="Site storage name already exists")
    assigned = await pb.list_records(
        collection="sites",
        token=token,
        filter=f'bucket_name="{sanitize_filter_value(bucket)}"',
        per_page=1,
    )
    if assigned.get("items"):
        raise HTTPException(status_code=409, detail="Site storage name is reserved")
    # PocketBase's unique site_id reserves the identity before external creation.
    record = await pb.create_record(
        collection="sites",
        data={**data, "bucket_name": bucket},
        token=token,
        user_id=user_id,
    )
    created = False
    try:
        await storage.create_bucket(bucket)
        created = True
        await storage.set_bucket_public_policy(bucket)
        if base_domain:
            await storage.set_bucket_cors(
                bucket, [f"https://{base_domain}", f"https://*.{base_domain}"]
            )
    except Exception:
        try:
            if created:
                await storage.delete_bucket(bucket)
            await pb.delete_record(
                collection="sites", record_id=record["id"], token=token
            )
        except Exception:
            logger.exception(
                "site provisioning rollback incomplete", extra={"site_id": site_id}
            )
        raise
    return record


async def delete_site_record(
    pb: PocketBaseClient,
    record: dict[str, Any],
    token: str,
    user_id: str | None = None,
) -> None:
    """Retain resources; caller holds the domain and site lifecycle locks."""
    async with operation_lock("build-lifecycle"):
        current = await pb.find_record_by_id("sites", record["id"], token=token)
        config = current.get("config") or {}
        lifecycle = config.get("_nexa_lifecycle") or {}
        if lifecycle.get("deleted_at"):
            return
        if current.get("serve_status") in {"verifying", "verified", "serving", "live"}:
            raise HTTPException(409, "Stop the site before deleting it")
        active = await pb.list_records(
            collection="builds",
            token=token,
            per_page=1,
            filter=f'site_id="{sanitize_filter_value(current["site_id"])}" && (status="queued" || status="building")',
        )
        if active.get("items"):
            raise HTTPException(409, "Wait for active builds before deleting the site")
        await pb.update_record(
            collection="sites",
            record_id=current["id"],
            token=token,
            user_id=user_id,
            data={
                "default": False,
                "config": {
                    **config,
                    "_nexa_lifecycle": {
                        "deleted_at": datetime.now(UTC).isoformat(),
                        "deleted_by": user_id,
                        "resource_policy": "retain",
                        "cleanup_status": "retained",
                        "bucket_name": current.get("bucket_name"),
                        "domain_id": current.get("domain_id"),
                    },
                },
            },
        )
