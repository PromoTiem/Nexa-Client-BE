from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Response

from app.application.services.storage_service import StorageFileService
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_storage_file_service,
    get_tenant_context,
)
from app.interface.dto.storage import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    DownloadUrlResponse,
    ItemResult,
    StorageFileResponse,
    StorageListResponse,
    StorageUpdateRequest,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import validate_id

router = APIRouter()


def _record_to_response(record: Dict[str, Any]) -> StorageFileResponse:
    return StorageFileResponse(
        file_id=record["file_id"],
        site_id=record["site_id"],
        page_id=record.get("page_id"),
        name=record["name"],
        original_name=record["original_name"],
        mime_type=record["mime_type"],
        size=record["size"],
        status=record["status"],
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
    )


@router.post("/upload-url", response_model=UploadUrlResponse, status_code=201)
async def create_upload_url(
    body: UploadUrlRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: StorageFileService = Depends(get_storage_file_service),
) -> UploadUrlResponse:
    enforce_permission(ctx.auth, Permission.STORAGE_ACCESS)
    validate_id(body.site_id, "site_id")
    if body.page_id is not None:
        validate_id(body.page_id, "page_id")
    await ctx.enforce_site(pb, body.site_id)
    result = await service.create_upload(
        site_id=body.site_id,
        filename=body.filename,
        content_type=body.content_type,
        declared_size=body.size,
        name=body.name,
        page_id=body.page_id,
        pb=pb,
        token=ctx.token,
        user_id=ctx.user_id,
    )
    return UploadUrlResponse(
        file_id=result["file_id"],
        upload_url=result["upload_url"],
        expires_at=result["expires_at"],
        bucket=result["bucket"],
        key=result["key"],
    )


@router.post("/{file_id}/confirm", response_model=StorageFileResponse)
async def confirm_upload(
    file_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: StorageFileService = Depends(get_storage_file_service),
) -> StorageFileResponse:
    enforce_permission(ctx.auth, Permission.STORAGE_ACCESS)
    validate_id(file_id, "file_id")
    record = await service.get_record(file_id, pb, ctx.token)
    await ctx.enforce_file(pb, record)
    record = await service.confirm_upload(
        file_id, pb, ctx.token, ctx.user_id
    )
    return _record_to_response(record)


@router.get("", response_model=StorageListResponse)
async def list_storage(
    site_id: str = Query(...),
    page_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: StorageFileService = Depends(get_storage_file_service),
) -> StorageListResponse:
    enforce_permission(ctx.auth, Permission.STORAGE_ACCESS)
    validate_id(site_id, "site_id")
    if page_id is not None:
        validate_id(page_id, "page_id")
    await ctx.enforce_site(pb, site_id)
    result = await service.list_files(
        site_id, page_id, page, limit, pb, ctx.token
    )
    items = [_record_to_response(r) for r in result.get("items", [])]
    return StorageListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", limit),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/{file_id}", response_model=StorageFileResponse)
async def get_storage(
    file_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: StorageFileService = Depends(get_storage_file_service),
) -> StorageFileResponse:
    enforce_permission(ctx.auth, Permission.STORAGE_ACCESS)
    validate_id(file_id, "file_id")
    record = await service.get_record(file_id, pb, ctx.token)
    await ctx.enforce_file(pb, record)
    return _record_to_response(record)


@router.get("/{file_id}/download-url", response_model=DownloadUrlResponse)
async def get_download_url(
    file_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: StorageFileService = Depends(get_storage_file_service),
) -> DownloadUrlResponse:
    enforce_permission(ctx.auth, Permission.STORAGE_ACCESS)
    validate_id(file_id, "file_id")
    record = await service.get_record(file_id, pb, ctx.token)
    await ctx.enforce_file(pb, record)
    download_url, expires_at = await service.get_download_url(
        file_id, pb, ctx.token
    )
    return DownloadUrlResponse(download_url=download_url, expires_at=expires_at)


@router.patch("/{file_id}", response_model=StorageFileResponse)
async def update_storage(
    file_id: str,
    body: StorageUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: StorageFileService = Depends(get_storage_file_service),
) -> StorageFileResponse:
    enforce_permission(ctx.auth, Permission.STORAGE_ACCESS)
    validate_id(file_id, "file_id")
    updates: Dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.page_id is not None:
        validate_id(body.page_id, "page_id")
        updates["page_id"] = body.page_id
    if not updates:
        record = await service.get_record(file_id, pb, ctx.token)
        await ctx.enforce_file(pb, record)
        return _record_to_response(record)
    record = await service.get_record(file_id, pb, ctx.token)
    await ctx.enforce_file(pb, record)
    record = await service.update_metadata(
        file_id, updates, pb, ctx.token, ctx.user_id
    )
    return _record_to_response(record)


@router.delete("/{file_id}", status_code=204)
async def delete_storage(
    file_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: StorageFileService = Depends(get_storage_file_service),
) -> Response:
    enforce_permission(ctx.auth, Permission.STORAGE_ACCESS)
    validate_id(file_id, "file_id")
    record = await service.get_record(file_id, pb, ctx.token)
    await ctx.enforce_file(pb, record)
    await service.delete_file(file_id, pb, ctx.token, ctx.user_id)
    return Response(status_code=204)


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_storage(
    body: BulkDeleteRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    service: StorageFileService = Depends(get_storage_file_service),
) -> BulkDeleteResponse:
    enforce_permission(ctx.auth, Permission.STORAGE_ACCESS)
    results = await service.bulk_delete(
        body.file_ids, pb, ctx.token, ctx.user_id, auth=ctx.auth
    )
    return BulkDeleteResponse(results=[ItemResult(**r) for r in results])
