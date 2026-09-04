from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import combine_filter, tenant_filter, validate_id
from app.interface.dto.page import PageResponse, PageListResponse

COLLECTION = "pages"

router = APIRouter()
logger = get_logger("page_routes")


def _record_to_response(record: Dict[str, Any]) -> PageResponse:
    return PageResponse(
        id=record["id"],
        page_id=record["page_id"],
        name=record.get("name", ""),
        slug=record.get("slug") or None,
        style_id=record.get("style_id") or None,
        layout=record.get("layout") or None,
        settings=record.get("settings") or None,
        section_ids=record.get("section_ids") or None,
        block_ids=record.get("block_ids") or None,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


@router.get("", response_model=PageListResponse)
async def list_pages(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-created_at"),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PageListResponse:
    enforce_permission(ctx.auth, Permission.PAGES_LIST)
    tenant_clause = await tenant_filter(pb, ctx.token, ctx.tenant_id)
    result = await pb.list_records(
        collection=COLLECTION,
        token=ctx.token,
        filter=tenant_clause,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = [_record_to_response(r) for r in result.get("items", [])]
    return PageListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/{page_id}", response_model=PageResponse)
async def get_page(
    page_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PageResponse:
    enforce_permission(ctx.auth, Permission.PAGES_LIST)
    validate_id(page_id, "page_id")
    tenant_clause = await tenant_filter(pb, ctx.token, ctx.tenant_id)
    lookup_filter = combine_filter(f'page_id="{page_id}"', tenant_clause)
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=lookup_filter,
        token=ctx.token,
    )
    return _record_to_response(record)
