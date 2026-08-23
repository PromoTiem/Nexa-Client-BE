from typing import Any

from fastapi import APIRouter, Depends, Query

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.dto.block import BlockListResponse, BlockResponse
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import validate_id

COLLECTION = "blocks"

router = APIRouter()
logger = get_logger("block_routes")


def _record_to_response(record: dict[str, Any]) -> BlockResponse:
    return BlockResponse(
        id=record["id"],
        block_id=record["block_id"],
        name=record.get("name", ""),
        type=record.get("type", ""),
        order_index=record.get("order_index") or None,
        props=record.get("props") or None,
        style=record.get("style") or None,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


@router.get("", response_model=BlockListResponse)
async def list_blocks(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-created_at"),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BlockListResponse:
    enforce_permission(ctx.auth, Permission.BLOCKS_LIST)
    result = await pb.list_records(
        collection=COLLECTION,
        token=ctx.token,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = [_record_to_response(r) for r in result.get("items", [])]
    return BlockListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/{block_id}", response_model=BlockResponse)
async def get_block(
    block_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BlockResponse:
    enforce_permission(ctx.auth, Permission.BLOCKS_LIST)
    validate_id(block_id, "block_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'block_id="{block_id}"',
        token=ctx.token,
    )
    return _record_to_response(record)
