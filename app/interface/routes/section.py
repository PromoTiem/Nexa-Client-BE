from typing import Any

from fastapi import APIRouter, Depends, Query

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.dto.section import SectionListResponse, SectionResponse
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import validate_id

COLLECTION = "sections"

router = APIRouter()
logger = get_logger("section_routes")


def _record_to_response(record: dict[str, Any]) -> SectionResponse:
    return SectionResponse(
        id=record["id"],
        section_id=record["section_id"],
        name=record.get("name", ""),
        layout=record.get("layout") or None,
        order_index=record.get("order_index") or None,
        block_ids=record.get("block_ids") or None,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


@router.get("", response_model=SectionListResponse)
async def list_sections(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-created_at"),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> SectionListResponse:
    enforce_permission(ctx.auth, Permission.SECTIONS_LIST)
    result = await pb.list_records(
        collection=COLLECTION,
        token=ctx.token,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = [_record_to_response(r) for r in result.get("items", [])]
    return SectionListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/{section_id}", response_model=SectionResponse)
async def get_section(
    section_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> SectionResponse:
    enforce_permission(ctx.auth, Permission.SECTIONS_LIST)
    validate_id(section_id, "section_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'section_id="{section_id}"',
        token=ctx.token,
    )
    return _record_to_response(record)
