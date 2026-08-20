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
from app.interface.route_helpers import validate_id
from app.interface.dto.style import StyleResponse, StyleListResponse

COLLECTION = "styles"

router = APIRouter()
logger = get_logger("style_routes")


def _record_to_response(record: Dict[str, Any]) -> StyleResponse:
    return StyleResponse(
        id=record["id"],
        style_id=record["style_id"],
        name=record.get("name", ""),
        description=record.get("description") or None,
        config=record.get("config") or None,
        tailwind_css=record.get("tailwindCss") or None,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


@router.get("", response_model=StyleListResponse)
async def list_styles(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-created_at"),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> StyleListResponse:
    enforce_permission(ctx.auth, Permission.STYLES_LIST)
    result = await pb.list_records(
        collection=COLLECTION,
        token=ctx.token,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = [_record_to_response(r) for r in result.get("items", [])]
    return StyleListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/{style_id}", response_model=StyleResponse)
async def get_style(
    style_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> StyleResponse:
    enforce_permission(ctx.auth, Permission.STYLES_LIST)
    validate_id(style_id, "style_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'style_id="{style_id}"',
        token=ctx.token,
    )
    return _record_to_response(record)
