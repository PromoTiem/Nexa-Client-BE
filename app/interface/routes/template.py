from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import AuthContext, get_auth_context, get_pocketbase_client
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import validate_id
from app.interface.dto.template import TemplateResponse, TemplateListResponse

COLLECTION = "templates"

router = APIRouter()
logger = get_logger("template_routes")


def _record_to_response(record: Dict[str, Any]) -> TemplateResponse:
    return TemplateResponse(
        id=record["id"],
        template_id=record["template_id"],
        name=record.get("name", ""),
        style_id=record.get("style_id") or None,
        category=record.get("category") or None,
        tags=record.get("tags") or None,
        description=record.get("description") or None,
        page_ids=record.get("page_ids") or None,
        version=record.get("version") or None,
        is_valid=record.get("is_valid") or None,
        default=record.get("default") or False,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


async def _resolve_style(
    pb: PocketBaseClient,
    token: str,
    style_id: Optional[str],
    warnings: List[str],
) -> Optional[Dict[str, Any]]:
    if not style_id:
        return None
    try:
        return await pb.find_one_by_filter(
            collection="styles",
            filter_expr=f'style_id="{style_id}"',
            token=token,
        )
    except Exception:
        warnings.append(f"style_id '{style_id}' not found")
        return None


async def _resolve_pages(
    pb: PocketBaseClient,
    token: str,
    page_ids: Optional[List[str]],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    if not page_ids:
        return []
    pages = []
    for pid in page_ids:
        try:
            page = await pb.find_one_by_filter(
                collection="pages",
                filter_expr=f'page_id="{pid}"',
                token=token,
            )
            pages.append(page)
        except Exception:
            warnings.append(f"page_id '{pid}' not found")
    return pages


async def _resolve_sections(
    pb: PocketBaseClient,
    token: str,
    section_ids: Optional[List[str]],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    if not section_ids:
        return []
    sections = []
    for sid in section_ids:
        try:
            section = await pb.find_one_by_filter(
                collection="sections",
                filter_expr=f'section_id="{sid}"',
                token=token,
            )
            sections.append(section)
        except Exception:
            warnings.append(f"section_id '{sid}' not found")
    return sections


async def _resolve_blocks(
    pb: PocketBaseClient,
    token: str,
    block_ids: Optional[List[str]],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    if not block_ids:
        return []
    blocks = []
    for bid in block_ids:
        try:
            block = await pb.find_one_by_filter(
                collection="blocks",
                filter_expr=f'block_id="{bid}"',
                token=token,
            )
            blocks.append(block)
        except Exception:
            warnings.append(f"block_id '{bid}' not found")
    return blocks


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-created_at"),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> TemplateListResponse:
    enforce_permission(auth, Permission.TEMPLATES_LIST)
    filter_parts: List[str] = []
    if category:
        filter_parts.append(f'category="{category}"')
    if tags:
        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                filter_parts.append(f'~tags~"{tag}"')
    if search:
        filter_parts.append(f'(name~"{search}" || description~"{search}")')

    filter_expr = " && ".join(filter_parts) if filter_parts else None

    result = await pb.list_records(
        collection=COLLECTION,
        token=auth.token,
        filter=filter_expr,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = [_record_to_response(r) for r in result.get("items", [])]
    return TemplateListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    expand: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> TemplateResponse:
    enforce_permission(auth, Permission.TEMPLATES_LIST)
    validate_id(template_id, "template_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'template_id="{template_id}"',
        token=auth.token,
    )
    resp = _record_to_response(record)

    if not expand:
        return resp

    expand_set = {"style", "pages", "sections", "blocks"} if expand == "true" else set(expand.split(","))
    warnings: List[str] = list(resp.warnings) if resp.warnings else []

    if "style" in expand_set:
        resp.expanded_style = await _resolve_style(pb, auth.token, resp.style_id, warnings)

    if "pages" in expand_set:
        resp.expanded_pages = await _resolve_pages(pb, auth.token, resp.page_ids, warnings)

    if resp.expanded_pages and "sections" in expand_set:
        for page in resp.expanded_pages:
            page["expanded_sections"] = await _resolve_sections(
                pb, auth.token, page.get("section_ids"), warnings
            )

    if resp.expanded_pages and "sections" in expand_set and "blocks" in expand_set:
        for page in resp.expanded_pages:
            for section in page.get("expanded_sections", []):
                section["expanded_blocks"] = await _resolve_blocks(
                    pb, auth.token, section.get("block_ids"), warnings
                )
    elif resp.expanded_pages and "blocks" in expand_set:
        for page in resp.expanded_pages:
            page["expanded_blocks"] = await _resolve_blocks(
                pb, auth.token, page.get("block_ids"), warnings
            )

    if warnings:
        resp.warnings = warnings

    return resp
