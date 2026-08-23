from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.services.media_service import MediaService
from app.application.services.storage_service import StorageFileService
from app.config import Settings, get_settings
from app.infrastructure.cloudflare.client import CloudflareClient
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.storage.client import StorageClient
from app.interface.auth_models import (
    AuthContext,
)
from app.interface.route_helpers import (
    ensure_file_tenant,
    ensure_site_tenant,
    ensure_tenant_owns,
)

logger = get_logger("auth")

_bearer = HTTPBearer(auto_error=False)


def get_pocketbase_client(
    settings: Settings = Depends(get_settings),
) -> PocketBaseClient:
    return PocketBaseClient(
        base_url=settings.pocketbase_url,
        timeout=settings.pocketbase_timeout,
        max_retries=settings.pocketbase_max_retries,
        retry_backoff=settings.pocketbase_retry_backoff,
    )


def get_cloudflare_client(
    settings: Settings = Depends(get_settings),
) -> CloudflareClient:
    return CloudflareClient(
        api_token=settings.cloudflare_api_token,
        account_id=settings.cloudflare_account_id,
        zone_id=settings.cloudflare_zone_id,
        timeout=settings.cloudflare_timeout,
        max_retries=settings.cloudflare_max_retries,
        retry_backoff=settings.cloudflare_retry_backoff,
    )


def get_storage_client(
    settings: Settings = Depends(get_settings),
) -> StorageClient:
    s = settings.storage
    return StorageClient(
        endpoint_url=s.endpoint_url,
        public_endpoint_url=s.public_endpoint_url,
        access_key=s.access_key,
        secret_key=s.secret_key,
        region=s.region,
        presign_expiry_seconds=s.presign_expiry_seconds,
    )


def get_media_service(
    settings: Settings = Depends(get_settings),
    storage: StorageClient = Depends(get_storage_client),
) -> MediaService:
    s = settings.storage
    return MediaService(
        storage_client=storage,
        max_file_bytes=s.max_file_bytes,
    )


def get_storage_file_service(
    settings: Settings = Depends(get_settings),
    storage: StorageClient = Depends(get_storage_client),
) -> StorageFileService:
    s = settings.storage
    return StorageFileService(
        storage_client=storage,
        max_file_bytes=s.max_file_bytes,
    )


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AuthContext:
    if not credentials:
        logger.warning("missing token")
        raise HTTPException(status_code=401, detail="Missing authorization token")
    try:
        data = await pb.auth_refresh(
            collection=settings.pocketbase_auth_collection,
            token=credentials.credentials,
        )
    except HTTPException as exc:
        logger.warning(
            "refresh failed",
            extra={"status": exc.status_code, "detail": str(exc.detail)},
        )
        raise
    if not data["record"].get("tenant_id"):
        logger.warning("client auth missing tenant_id")
        raise HTTPException(status_code=403, detail="Client access requires tenant_id")
    return AuthContext(token=data["token"], record=data["record"])


@dataclass
class TenantContext:
    auth: AuthContext
    tenant_id: str | None

    @property
    def token(self) -> str:
        return self.auth.token

    @property
    def user_id(self) -> str:
        return self.auth.record["id"]

    def owns(self, record: dict[str, Any]) -> bool:
        if not self.tenant_id:
            return True
        return record.get("tenant_id") == self.tenant_id

    def enforce_owns(self, record: dict[str, Any]) -> None:
        ensure_tenant_owns(record, self.auth)

    async def enforce_site(self, pb: PocketBaseClient, site_id: str) -> None:
        await ensure_site_tenant(pb, site_id, self.auth)

    async def enforce_file(self, pb: PocketBaseClient, record: dict[str, Any]) -> None:
        await ensure_file_tenant(pb, record, self.auth)


async def get_tenant_context(
    auth: AuthContext = Depends(get_auth_context),
) -> TenantContext:
    return TenantContext(
        auth=auth,
        tenant_id=auth.record.get("tenant_id"),
    )


async def get_optional_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AuthContext | None:
    if not credentials:
        return None
    try:
        data = await pb.auth_refresh(
            collection=settings.pocketbase_auth_collection,
            token=credentials.credentials,
        )
    except HTTPException as exc:
        logger.warning(
            "refresh failed",
            extra={"status": exc.status_code, "detail": str(exc.detail)},
        )
        raise
    if not data["record"].get("tenant_id"):
        logger.warning("client auth missing tenant_id")
        raise HTTPException(status_code=403, detail="Client access requires tenant_id")
    return AuthContext(token=data["token"], record=data["record"])
