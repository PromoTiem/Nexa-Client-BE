from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from app.application.services.constants import SOFT_DELETE_FILTER
from app.application.services.property_service import PropertyService
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_static_pocketbase_client,
    get_tenant_context,
)
from app.interface.dto.property import (
    PropertyCreateRequest,
    PropertyListResponse,
    PropertyResponse,
    PropertyUpdateRequest,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import (
    build_filter,
    sanitize_filter_value,
    validate_id,
    validate_sort,
)

COLLECTION = "properties"

router = APIRouter()
public_property_router = APIRouter()

logger = get_logger("property_routes")


def _record_to_response(record: dict[str, Any]) -> PropertyResponse:
    return PropertyResponse(
        id=record["id"],
        property_id=record["property_id"],
        site_id=record["site_id"],
        type=record.get("type"),
        subtype=record.get("subtype"),
        name=record["name"],
        slug=record.get("slug"),
        status=record.get("status", "draft"),
        excerpt=record.get("excerpt"),
        featured_image=record.get("featured_image"),
        seo=record.get("seo"),
        published_at=record.get("published_at"),
        fields=record.get("fields", []),
        groups=record.get("groups", []),
        metadata=record.get("metadata"),
        ordering=record.get("ordering", 0),
        deleted_at=record.get("deleted_at"),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


# ------------------------------------------------------------------ #
# POST /sites/{site_id}/properties                                    #
# ------------------------------------------------------------------ #


@router.post(
    "/sites/{site_id}/properties",
    response_model=PropertyResponse,
    status_code=201,
)
async def create_property(
    site_id: str,
    body: PropertyCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PropertyResponse:
    enforce_permission(ctx.auth, Permission.PROPERTIES_CREATE)
    validate_id(site_id, "site_id")
    validate_id(body.property_id, "property_id")
    await ctx.enforce_site(pb, site_id)

    service = PropertyService()
    record = await service.create_property(
        pb=pb,
        token=ctx.token,
        user_id=ctx.user_id,
        site_id=site_id,
        data={
            "property_id": body.property_id,
            "type": body.type,
            "subtype": body.subtype,
            "name": body.name,
            "slug": body.slug,
            "status": body.status,
            "excerpt": body.excerpt,
            "featured_image": body.featured_image,
            "seo": body.seo,
            "fields": body.fields,
            "groups": body.groups,
            "metadata": body.metadata,
            "ordering": body.ordering,
        },
    )
    return _record_to_response(record)


# ------------------------------------------------------------------ #
# GET /sites/{site_id}/properties                                     #
# ------------------------------------------------------------------ #


@router.get(
    "/sites/{site_id}/properties",
    response_model=PropertyListResponse,
)
async def list_properties(
    site_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-ordering"),
    type: str | None = Query(None),
    subtype: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    slug: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PropertyListResponse:
    enforce_permission(ctx.auth, Permission.PROPERTIES_LIST)
    validate_id(site_id, "site_id")
    await ctx.enforce_site(pb, site_id)
    sort = validate_sort(
        sort, allowed_fields=["ordering", "created_at", "updated_at", "name", "status"]
    )

    filter_parts: list[str] = [
        f'site_id="{site_id}"',
        SOFT_DELETE_FILTER,
    ]
    if type:
        filter_parts.append(f'type="{sanitize_filter_value(type)}"')
    if subtype:
        filter_parts.append(f'subtype="{sanitize_filter_value(subtype)}"')
    if status:
        filter_parts.append(f'status="{sanitize_filter_value(status)}"')
    if search:
        filter_parts.append(f'name~"{sanitize_filter_value(search)}"')
    if slug:
        filter_parts.append(f'slug="{sanitize_filter_value(slug)}"')

    result = await pb.list_records(
        collection=COLLECTION,
        token=ctx.token,
        filter=build_filter(filter_parts),
        sort=sort,
        page=page,
        per_page=per_page,
    )
    return PropertyListResponse(
        items=[_record_to_response(r) for r in result.get("items", [])],
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


# ------------------------------------------------------------------ #
# GET /properties/{property_id}                                       #
# ------------------------------------------------------------------ #


@router.get(
    "/properties/{property_id}",
    response_model=PropertyResponse,
)
async def get_property(
    property_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PropertyResponse:
    enforce_permission(ctx.auth, Permission.PROPERTIES_LIST)
    validate_id(property_id, "property_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'property_id="{property_id}" && {SOFT_DELETE_FILTER}',
        token=ctx.token,
    )
    await ctx.enforce_site(pb, record["site_id"])
    return _record_to_response(record)


# ------------------------------------------------------------------ #
# PATCH /properties/{property_id}                                     #
# ------------------------------------------------------------------ #


@router.patch(
    "/properties/{property_id}",
    response_model=PropertyResponse,
)
async def update_property(
    property_id: str,
    body: PropertyUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PropertyResponse:
    enforce_permission(ctx.auth, Permission.PROPERTIES_UPDATE)
    validate_id(property_id, "property_id")
    existing = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'property_id="{property_id}" && {SOFT_DELETE_FILTER}',
        token=ctx.token,
    )
    await ctx.enforce_site(pb, existing["site_id"])

    updates: dict[str, Any] = {}
    if body.type is not None:
        updates["type"] = body.type
    if body.subtype is not None:
        updates["subtype"] = body.subtype
    if body.name is not None:
        updates["name"] = body.name
    if body.slug is not None:
        updates["slug"] = body.slug
    if body.status is not None:
        updates["status"] = body.status
    if body.excerpt is not None:
        updates["excerpt"] = body.excerpt
    if body.featured_image is not None:
        updates["featured_image"] = body.featured_image
    if body.seo is not None:
        updates["seo"] = body.seo
    if body.fields is not None:
        updates["fields"] = body.fields
    if body.groups is not None:
        updates["groups"] = body.groups
    if body.metadata is not None:
        updates["metadata"] = body.metadata
    if body.ordering is not None:
        updates["ordering"] = body.ordering

    if not updates:
        return _record_to_response(existing)

    service = PropertyService()
    record = await service.update_property(
        pb=pb,
        token=ctx.token,
        user_id=ctx.user_id,
        record=existing,
        updates=updates,
    )
    return _record_to_response(record)


# ------------------------------------------------------------------ #
# DELETE /properties/{property_id}                                    #
# ------------------------------------------------------------------ #


@router.delete(
    "/properties/{property_id}",
    status_code=204,
)
async def delete_property(
    property_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    enforce_permission(ctx.auth, Permission.PROPERTIES_DELETE)
    validate_id(property_id, "property_id")
    existing = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'property_id="{property_id}" && {SOFT_DELETE_FILTER}',
        token=ctx.token,
    )
    await ctx.enforce_site(pb, existing["site_id"])

    service = PropertyService()
    await service.soft_delete_property(
        pb=pb,
        token=ctx.token,
        user_id=ctx.user_id,
        record=existing,
    )
    return Response(status_code=204)


# ------------------------------------------------------------------ #
# Public routes (prefix /public)                                     #
# ------------------------------------------------------------------ #


@public_property_router.post(
    "/sites/{site_id}/properties",
    response_model=PropertyResponse,
    status_code=201,
)
async def create_public_property(
    site_id: str,
    body: PropertyCreateRequest,
    pb: PocketBaseClient = Depends(get_static_pocketbase_client),
) -> PropertyResponse:
    validate_id(site_id, "site_id")
    validate_id(body.property_id, "property_id")

    service = PropertyService()
    record = await service.create_property(
        pb=pb,
        token=pb._static_token,
        user_id="",
        site_id=site_id,
        data={
            "property_id": body.property_id,
            "type": body.type,
            "subtype": body.subtype,
            "name": body.name,
            "slug": body.slug,
            "status": body.status,
            "excerpt": body.excerpt,
            "featured_image": body.featured_image,
            "seo": body.seo,
            "fields": body.fields,
            "groups": body.groups,
            "metadata": body.metadata,
            "ordering": body.ordering,
        },
    )
    return _record_to_response(record)
