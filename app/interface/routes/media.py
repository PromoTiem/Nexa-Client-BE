from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Response

from app.application.services.media_service import MediaService
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    AuthContext,
    get_auth_context,
    get_media_service,
    get_pocketbase_client,
)
from app.interface.dto.media import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    DownloadUrlResponse,
    ItemResult,
    MediaListResponse,
    MediaResponse,
    MediaUpdateRequest,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import (
    ensure_file_tenant,
    ensure_site_tenant,
    validate_id,
)

router = APIRouter()


def _record_to_response(record: Dict[str, Any]) -> MediaResponse:
    return MediaResponse(
        file_id=record["file_id"],
        site_id=record["site_id"],
        page_id=record.get("page_id"),
        original_file_id=record.get("original_file_id"),
        name=record["name"],
        original_name=record["original_name"],
        mime_type=record["mime_type"],
        size=record["size"],
        status=record["status"],
        is_default=record.get("is_default", False),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
    )


@router.post("/upload-url", response_model=UploadUrlResponse, status_code=201)
async def create_upload_url(
    body: UploadUrlRequest,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: MediaService = Depends(get_media_service),
) -> UploadUrlResponse:
    enforce_permission(auth, Permission.MEDIA_UPLOAD)
    validate_id(body.site_id, "site_id")
    if body.page_id is not None:
        validate_id(body.page_id, "page_id")
    if body.original_file_id is not None:
        validate_id(body.original_file_id, "file_id")
    await ensure_site_tenant(pb, body.site_id, auth)
    result = await service.create_upload(
        site_id=body.site_id,
        filename=body.filename,
        content_type=body.content_type,
        declared_size=body.size,
        name=body.name,
        is_default=bool(body.is_default),
        original_file_id=body.original_file_id,
        page_id=body.page_id,
        pb=pb,
        token=auth.token,
        user_id=auth.record["id"],
    )
    return UploadUrlResponse(
        file_id=result["file_id"],
        upload_url=result["upload_url"],
        expires_at=result["expires_at"],
        bucket=result["bucket"],
        key=result["key"],
    )


@router.post("/{file_id}/confirm", response_model=MediaResponse)
async def confirm_upload(
    file_id: str,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: MediaService = Depends(get_media_service),
) -> MediaResponse:
    enforce_permission(auth, Permission.MEDIA_UPLOAD)
    validate_id(file_id, "file_id")
    record = await service.get_record(file_id, pb, auth.token)
    await ensure_file_tenant(pb, record, auth)
    record = await service.confirm_upload(
        file_id, pb, auth.token, auth.record["id"]
    )
    return _record_to_response(record)


@router.get("", response_model=MediaListResponse)
async def list_media(
    site_id: str = Query(...),
    page_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: MediaService = Depends(get_media_service),
) -> MediaListResponse:
    enforce_permission(auth, Permission.MEDIA_LIST)
    validate_id(site_id, "site_id")
    if page_id is not None:
        validate_id(page_id, "page_id")
    await ensure_site_tenant(pb, site_id, auth)
    result = await service.list_media(
        site_id, page_id, page, limit, pb, auth.token
    )
    items = [_record_to_response(r) for r in result.get("items", [])]
    return MediaListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", limit),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/{file_id}", response_model=MediaResponse)
async def get_media(
    file_id: str,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: MediaService = Depends(get_media_service),
) -> MediaResponse:
    enforce_permission(auth, Permission.MEDIA_LIST)
    validate_id(file_id, "file_id")
    record = await service.get_record(file_id, pb, auth.token)
    await ensure_file_tenant(pb, record, auth)
    return _record_to_response(record)


@router.get("/{file_id}/download-url", response_model=DownloadUrlResponse)
async def get_download_url(
    file_id: str,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: MediaService = Depends(get_media_service),
) -> DownloadUrlResponse:
    enforce_permission(auth, Permission.MEDIA_LIST)
    validate_id(file_id, "file_id")
    record = await service.get_record(file_id, pb, auth.token)
    await ensure_file_tenant(pb, record, auth)
    download_url, expires_at = await service.get_download_url(
        file_id, pb, auth.token
    )
    return DownloadUrlResponse(
        download_url=download_url, expires_at=expires_at
    )


@router.patch("/{file_id}", response_model=MediaResponse)
async def update_media(
    file_id: str,
    body: MediaUpdateRequest,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: MediaService = Depends(get_media_service),
) -> MediaResponse:
    enforce_permission(auth, Permission.MEDIA_UPLOAD)
    validate_id(file_id, "file_id")
    updates: Dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.is_default is not None:
        updates["is_default"] = body.is_default
    if body.original_file_id is not None:
        validate_id(body.original_file_id, "file_id")
        updates["original_file_id"] = body.original_file_id
    if body.page_id is not None:
        validate_id(body.page_id, "page_id")
        updates["page_id"] = body.page_id
    if not updates:
        record = await service.get_record(file_id, pb, auth.token)
        await ensure_file_tenant(pb, record, auth)
        return _record_to_response(record)
    record = await service.get_record(file_id, pb, auth.token)
    await ensure_file_tenant(pb, record, auth)
    record = await service.update_metadata(
        file_id, updates, pb, auth.token, auth.record["id"]
    )
    return _record_to_response(record)


@router.delete("/{file_id}", status_code=204)
async def delete_media(
    file_id: str,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: MediaService = Depends(get_media_service),
) -> Response:
    enforce_permission(auth, Permission.MEDIA_DELETE)
    validate_id(file_id, "file_id")
    record = await service.get_record(file_id, pb, auth.token)
    await ensure_file_tenant(pb, record, auth)
    await service.delete_media(file_id, pb, auth.token, auth.record["id"])
    return Response(status_code=204)


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_media(
    body: BulkDeleteRequest,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: MediaService = Depends(get_media_service),
) -> BulkDeleteResponse:
    enforce_permission(auth, Permission.MEDIA_DELETE)
    results = await service.bulk_delete(body.file_ids, pb, auth.token, auth.record["id"], auth=auth)
    return BulkDeleteResponse(
        results=[ItemResult(**r) for r in results]
    )
