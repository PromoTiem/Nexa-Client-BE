from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.dto.build import (
    BuildCreateRequest,
    BuildListResponse,
    BuildResponse,
    BuildUpdateRequest,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import (
    build_filter,
    public_id_to_record_id,
    record_id_to_public_id,
    sanitize_filter_value,
    validate_id,
    validate_sort,
)

COLLECTION = "builds"

router = APIRouter()
logger = get_logger("build_routes")


def _record_to_response(record: dict[str, Any]) -> BuildResponse:
    return BuildResponse(
        id=record["id"],
        build_id=record["build_id"],
        site_id=record["site_id"],
        template_id=record.get("template_id"),
        status=record["status"],
        content_id=record.get("content_id"),
        config=record.get("config"),
        description=record.get("description"),
        error_message=record.get("error_message"),
        build_log=record.get("build_log"),
        image=record.get("image"),
        started_at=record.get("started_at"),
        completed_at=record.get("completed_at"),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


async def _resolve_site_tenant(site_id: str, pb: PocketBaseClient, token: str) -> str:
    site = await pb.find_one_by_filter(
        collection="sites",
        filter_expr=f'site_id="{site_id}"',
        token=token,
    )
    return site.get("tenant_id", "")


async def _enforce_build_tenant(
    record: dict[str, Any], ctx: TenantContext, pb: PocketBaseClient
) -> None:
    if not ctx.tenant_id:
        return
    site_tenant = await _resolve_site_tenant(record["site_id"], pb, ctx.token)
    site_tenant_public = await record_id_to_public_id(
        pb, "tenants", "tenant_id", site_tenant, ctx.token
    )
    if site_tenant_public != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="Build not found")


@router.get("", response_model=BuildListResponse)
async def list_builds(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-created_at"),
    site_id: str | None = Query(None),
    status: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BuildListResponse:
    enforce_permission(ctx.auth, Permission.BUILDS_LIST)
    sort = validate_sort(
        sort,
        allowed_fields=[
            "created_at",
            "updated_at",
            "status",
            "started_at",
            "completed_at",
        ],
    )
    filter_parts = []
    if ctx.tenant_id:
        tenant_record_id = await public_id_to_record_id(
            pb, "tenants", "tenant_id", ctx.tenant_id, ctx.token
        )
        filter_parts.append(f'tenant_id="{tenant_record_id}"')
    if site_id:
        filter_parts.append(f'site_id="{sanitize_filter_value(site_id)}"')
    if status:
        filter_parts.append(f'status="{sanitize_filter_value(status)}"')
    filter_expr = build_filter(filter_parts)

    result = await pb.list_records(
        collection=COLLECTION,
        token=ctx.token,
        filter=filter_expr,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = [_record_to_response(r) for r in result.get("items", [])]
    return BuildListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/{build_id}", response_model=BuildResponse)
async def get_build(
    build_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BuildResponse:
    enforce_permission(ctx.auth, Permission.BUILDS_LIST)
    validate_id(build_id, "build_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'build_id="{build_id}"',
        token=ctx.token,
    )
    await _enforce_build_tenant(record, ctx, pb)
    return _record_to_response(record)


@router.post("", response_model=BuildResponse, status_code=201)
async def create_build(
    body: BuildCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BuildResponse:
    enforce_permission(ctx.auth, Permission.BUILDS_CREATE)
    validate_id(body.build_id, "build_id")
    validate_id(body.site_id, "site_id")

    tenant = ctx.tenant_id
    if not tenant:
        raise HTTPException(status_code=403, detail="Client access requires tenant_id")

    tenant_record_id = await public_id_to_record_id(
        pb, "tenants", "tenant_id", tenant, ctx.token
    )

    site = await pb.find_one_by_filter(
        collection="sites",
        filter_expr=f'site_id="{body.site_id}"',
        token=ctx.token,
    )
    if site.get("tenant_id") != tenant_record_id:
        raise HTTPException(status_code=404, detail="Site not found")

    data: dict[str, Any] = {
        "build_id": body.build_id,
        "site_id": body.site_id,
        "status": "queued",
        "description": "Manual build",
        "tenant_id": tenant_record_id,
    }
    if body.template_id:
        validate_id(body.template_id, "template_id")
        data["template_id"] = body.template_id
    if body.content_id is not None:
        data["content_id"] = body.content_id
    if body.config is not None:
        data["config"] = body.config

    record = await pb.create_record(
        collection=COLLECTION,
        data=data,
        token=ctx.token,
        user_id=ctx.user_id,
    )
    logger.info(
        "build created via API",
        extra={"build_id": body.build_id, "site_id": body.site_id},
    )
    return _record_to_response(record)


@router.patch("/{build_id}", response_model=BuildResponse)
async def update_build(
    build_id: str,
    body: BuildUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BuildResponse:
    enforce_permission(ctx.auth, Permission.BUILDS_CREATE)
    validate_id(build_id, "build_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'build_id="{build_id}"',
        token=ctx.token,
    )
    await _enforce_build_tenant(record, ctx, pb)

    updates: dict[str, Any] = {}
    if body.status is not None:
        updates["status"] = body.status
    if body.content_id is not None:
        updates["content_id"] = body.content_id
    if body.config is not None:
        updates["config"] = body.config

    if updates:
        record = await pb.update_record(
            collection=COLLECTION,
            record_id=record["id"],
            data=updates,
            token=ctx.token,
            user_id=ctx.user_id,
        )
    return _record_to_response(record)


@router.delete("/{build_id}", status_code=204)
async def delete_build(
    build_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    enforce_permission(ctx.auth, Permission.BUILDS_DELETE)
    validate_id(build_id, "build_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'build_id="{build_id}"',
        token=ctx.token,
    )
    await _enforce_build_tenant(record, ctx, pb)
    await pb.delete_record(
        collection=COLLECTION,
        record_id=record["id"],
        token=ctx.token,
    )
    return Response(status_code=204)
