from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.services.media_service import MediaService
from app.application.services.storage_service import StorageFileService
from app.config import Settings, get_settings
from app.infrastructure.cloudflare.client import CloudflareClient
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient, create_static_pb_client
from app.infrastructure.storage.client import StorageClient

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


@dataclass
class AuthContext:
    token: str
    record: Dict[str, Any]


async def get_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AuthContext:
    if not credentials:
        logger.warning("missing token")
        raise HTTPException(
            status_code=401, detail="Missing authorization token"
        )
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
        raise HTTPException(
            status_code=403, detail="Client access requires tenant_id"
        )
    return AuthContext(token=data["token"], record=data["record"])


@dataclass
class SuperAdminContext:
    token: str


def get_static_pb_client(
    settings: Settings = Depends(get_settings),
) -> PocketBaseClient:
    return create_static_pb_client(settings=settings)


async def get_admin_context(
    x_api_be_token: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> SuperAdminContext:
    if not x_api_be_token:
        logger.warning("missing superadmin token")
        raise HTTPException(
            status_code=401, detail="Missing superadmin token"
        )
    if not settings.pocketbase_api_token:
        logger.error("pocketbase_api_token not configured")
        raise HTTPException(
            status_code=500, detail="Superadmin authentication not configured"
        )
    if x_api_be_token != settings.pocketbase_api_token:
        logger.warning("invalid superadmin token")
        raise HTTPException(
            status_code=401, detail="Invalid superadmin token"
        )
    return SuperAdminContext(token=x_api_be_token)
