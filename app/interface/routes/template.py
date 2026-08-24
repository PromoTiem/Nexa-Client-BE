from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import (
    build_filter,
    combine_filter,
    sanitize_filter_value,
    tenant_filter,
    validate_id,
    validate_sort,
)
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
        is_default=record.get("default") or False,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


async def _resolve_batch(
    pb: PocketBaseClient,
    token: str,
    collection: str,
    id_field: str,
    ids: Optional[List[str]],
    warnings: List[str],
    tenant_clause: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not ids:
        return []
    filter_expr = " || ".join(f'{id_field}="{id}"' for id in ids)
    if tenant_clause:
        filter_expr = f"({filter_expr}) && {tenant_clause}"
    try:
        result = await pb.list_records(
            collection=collection, token=token, filter=filter_expr, per_page=100
        )
        return result.get("items", [])
    except Exception:
        warnings.append(f"Failed to resolve {collection}")
        return []


async def _resolve_style(
    pb: PocketBaseClient,
    token: str,
    style_id: Optional[str],
    warnings: List[str],
    tenant_clause: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not style_id:
        return None
    filter_expr = f'style_id="{style_id}"'
    if tenant_clause:
        filter_expr = f"{filter_expr} && {tenant_clause}"
    try:
        return await pb.find_one_by_filter(
            collection="styles",
            filter_expr=filter_expr,
            token=token,
        )
    except Exception:
        warnings.append(f"style_id '{style_id}' not found")
        return None


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-created_at"),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> TemplateListResponse:
    enforce_permission(ctx.auth, Permission.TEMPLATES_LIST)
    sort = validate_sort(
        sort, allowed_fields=["created_at", "updated_at", "name", "category"]
    )
    filter_parts: List[str] = []
    if category:
        filter_parts.append(f'category="{sanitize_filter_value(category)}"')
    if tags:
        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                filter_parts.append(f'~tags~"{sanitize_filter_value(tag)}"')
    if search:
        sanitized_search = sanitize_filter_value(search)
        filter_parts.append(
            f'(name~"{sanitized_search}" || description~"{sanitized_search}")'
        )

    tenant_clause = await tenant_filter(pb, ctx.token, ctx.tenant_id)
    if tenant_clause:
        filter_parts.append(tenant_clause)

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
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> TemplateResponse:
    enforce_permission(ctx.auth, Permission.TEMPLATES_LIST)
    validate_id(template_id, "template_id")
    tenant_clause = await tenant_filter(pb, ctx.token, ctx.tenant_id)
    lookup_filter = combine_filter(f'template_id="{template_id}"', tenant_clause)
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=lookup_filter,
        token=ctx.token,
    )
    resp = _record_to_response(record)

    if not expand:
        return resp

    expand_set = {"style", "pages", "sections", "blocks"} if expand == "true" else set(expand.split(","))
    warnings: List[str] = list(resp.warnings) if resp.warnings else []

    if "style" in expand_set:
        resp.expanded_style = await _resolve_style(
            pb, ctx.token, resp.style_id, warnings, tenant_clause
        )

    if "pages" in expand_set:
        resp.expanded_pages = await _resolve_batch(
            pb, ctx.token, "pages", "page_id", resp.page_ids, warnings, tenant_clause
        )

    if resp.expanded_pages and "sections" in expand_set:
        all_section_ids = []
        for page in resp.expanded_pages:
            all_section_ids.extend(page.get("section_ids") or [])
        sections = await _resolve_batch(
            pb, ctx.token, "sections", "section_id", all_section_ids, warnings, tenant_clause
        )
        sections_by_id = {s["section_id"]: s for s in sections}
        for page in resp.expanded_pages:
            page["expanded_sections"] = [
                sections_by_id[sid]
                for sid in (page.get("section_ids") or [])
                if sid in sections_by_id
            ]

    if resp.expanded_pages and "blocks" in expand_set:
        all_block_ids = []
        if "sections" in expand_set:
            for page in resp.expanded_pages:
                for section in page.get("expanded_sections", []):
                    all_block_ids.extend(section.get("block_ids") or [])
            blocks = await _resolve_batch(
                pb, ctx.token, "blocks", "block_id", all_block_ids, warnings, tenant_clause
            )
            blocks_by_id = {b["block_id"]: b for b in blocks}
            for page in resp.expanded_pages:
                for section in page.get("expanded_sections", []):
                    section["expanded_blocks"] = [
                        blocks_by_id[bid]
                        for bid in (section.get("block_ids") or [])
                        if bid in blocks_by_id
                    ]
        else:
            for page in resp.expanded_pages:
                all_block_ids.extend(page.get("block_ids") or [])
            blocks = await _resolve_batch(
                pb, ctx.token, "blocks", "block_id", all_block_ids, warnings, tenant_clause
            )
            blocks_by_id = {b["block_id"]: b for b in blocks}
            for page in resp.expanded_pages:
                page["expanded_blocks"] = [
                    blocks_by_id[bid]
                    for bid in (page.get("block_ids") or [])
                    if bid in blocks_by_id
                ]

    if warnings:
        resp.warnings = warnings

    return resp
