from typing import Any

from fastapi import HTTPException

from app.application.services.bucket_resolver import sanitize_bucket_name
from app.application.services.site_deployer import (
    remove_dns_for_domain,
    remove_domain_from_pages,
    sanitize_project_name,
)
from app.infrastructure.cloudflare.client import CloudflareClient
from app.infrastructure.logging import get_logger
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


async def _ignore_missing(operation, *args) -> None:
    try:
        await operation(*args)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise


async def delete_site_record(
    pb: PocketBaseClient,
    cf: CloudflareClient,
    storage: StorageClient,
    record: dict[str, Any],
    token: str,
    base_domain: str,
) -> None:
    site_id = record["site_id"]
    bucket = record.get("bucket_name") or sanitize_bucket_name(site_id)
    # Fail closed on legacy shared assignments before deleting external resources.
    other = await pb.list_records(
        collection="sites",
        token=token,
        filter=f'id!="{sanitize_filter_value(record["id"])}" && bucket_name="{sanitize_filter_value(bucket)}"',
        per_page=1,
    )
    if other.get("items"):
        raise HTTPException(
            status_code=409, detail="Site bucket is shared; cleanup requires migration"
        )
    project = sanitize_project_name(site_id)
    derived_domain = f"{project}.{base_domain}"
    await _ignore_missing(remove_domain_from_pages, project, derived_domain, cf)
    await _ignore_missing(remove_dns_for_domain, derived_domain, cf)
    if record.get("domain_id"):
        try:
            domain = await pb.find_one_by_filter(
                collection="domains",
                filter_expr=f'id="{sanitize_filter_value(record["domain_id"])}"',
                token=token,
            )
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        else:
            if domain.get("domain"):
                await _ignore_missing(
                    remove_domain_from_pages, project, domain["domain"], cf
                )
                zone = await cf.resolve_zone_id(domain["domain"])
                records = await cf.list_dns_records(
                    zone, record_type="CNAME", name=domain["domain"]
                )
                for dns in records.get("result", []):
                    if (
                        dns.get("content", "").rstrip(".").lower()
                        == f"{project}.pages.dev"
                    ):
                        await _ignore_missing(cf.delete_dns_record, zone, dns["id"])
    await storage.empty_bucket(bucket)
    await storage.delete_bucket(bucket)
    # Retain the site as retry state until every required cleanup has succeeded.
    await pb.delete_record(collection="sites", record_id=record["id"], token=token)
