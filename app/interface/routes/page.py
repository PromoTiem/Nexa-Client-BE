from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import AuthContext, get_auth_context, get_pocketbase_client
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import validate_id
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
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PageListResponse:
    enforce_permission(auth, Permission.PAGES_LIST)
    result = await pb.list_records(
        collection=COLLECTION,
        token=auth.token,
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
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PageResponse:
    enforce_permission(auth, Permission.PAGES_LIST)
    validate_id(page_id, "page_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'page_id="{page_id}"',
        token=auth.token,
    )
    return _record_to_response(record)
