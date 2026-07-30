from typing import Optional

from app.application.services.utils import SITES_COLLECTION, sanitize_name
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.storage.client import StorageClient

logger = get_logger("bucket_resolver")


def sanitize_bucket_name(name: str) -> str:
    """Convert a site_id to a valid S3 bucket name (lowercase, hyphens only)."""
    return sanitize_name(name)


async def ensure_site_bucket(
    site_id: str,
    pb: PocketBaseClient,
    storage: StorageClient,
    token: Optional[str] = None,
) -> str:
    site = await pb.find_one_by_filter(
        collection=SITES_COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=token,
    )

    bucket_name = site.get("bucket_name") or sanitize_bucket_name(site_id)

    s3_exists = await storage.bucket_exists(bucket_name)
    if not s3_exists:
        await storage.create_bucket(bucket_name)
        await storage.set_bucket_public_policy(bucket_name)
        logger.info(
            "storage bucket created for site",
            extra={"site_id": site_id, "bucket": bucket_name},
        )

    if not site.get("bucket_name"):
        try:
            await pb.update_record(
                collection=SITES_COLLECTION,
                record_id=site["id"],
                data={"bucket_name": bucket_name},
                token=token,
            )
            logger.info(
                "site record updated with bucket_name",
                extra={"site_id": site_id, "bucket": bucket_name},
            )
        except Exception as e:
            logger.warning(
                "failed to update site record with bucket_name (field may not exist in schema)",
                extra={"site_id": site_id, "bucket": bucket_name, "error": str(e)},
            )

    return bucket_name


async def create_bucket_for_site(
    site_id: str,
    storage: StorageClient,
) -> None:
    bucket_name = sanitize_bucket_name(site_id)
    exists = await storage.bucket_exists(bucket_name)
    if not exists:
        await storage.create_bucket(bucket_name)
        await storage.set_bucket_public_policy(bucket_name)
        logger.info(
            "storage bucket created for site",
            extra={"site_id": site_id, "bucket": bucket_name},
        )


async def delete_bucket_for_site(
    bucket_name: str,
    storage: StorageClient,
) -> None:
    await storage.delete_bucket(bucket_name)
    logger.info(
        "storage bucket deleted for site",
        extra={"bucket": bucket_name},
    )
