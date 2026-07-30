from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.application.services.constants import SOFT_DELETE_FILTER
from app.application.services.property_service import PropertyService
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    AuthContext,
    get_auth_context,
    get_pocketbase_client,
)
from app.interface.dto.property import (
    PropertyCreateRequest,
    PropertyListResponse,
    PropertyResponse,
    PropertyUpdateRequest,
)
from app.interface.route_helpers import build_filter, ensure_site_tenant, validate_id

COLLECTION = "properties"

router = APIRouter()

logger = get_logger("property_routes")


def _record_to_response(record: Dict[str, Any]) -> PropertyResponse:
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
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PropertyResponse:
    validate_id(site_id, "site_id")
    validate_id(body.property_id, "property_id")
    await ensure_site_tenant(pb, site_id, auth)

    service = PropertyService()
    record = await service.create_property(
        pb=pb,
        token=auth.token,
        user_id=auth.record["id"],
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
    type: Optional[str] = Query(None),
    subtype: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    slug: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PropertyListResponse:
    validate_id(site_id, "site_id")
    await ensure_site_tenant(pb, site_id, auth)

    filter_parts: List[str] = [
        f'site_id="{site_id}"',
        SOFT_DELETE_FILTER,
    ]
    if type:
        filter_parts.append(f'type="{type}"')
    if subtype:
        filter_parts.append(f'subtype="{subtype}"')
    if status:
        filter_parts.append(f'status="{status}"')
    if search:
        filter_parts.append(f'name~"{search}"')
    if slug:
        filter_parts.append(f'slug="{slug}"')

    result = await pb.list_records(
        collection=COLLECTION,
        token=auth.token,
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
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PropertyResponse:
    validate_id(property_id, "property_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'property_id="{property_id}" && {SOFT_DELETE_FILTER}',
        token=auth.token,
    )
    await ensure_site_tenant(pb, record["site_id"], auth)
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
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PropertyResponse:
    validate_id(property_id, "property_id")
    existing = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'property_id="{property_id}" && {SOFT_DELETE_FILTER}',
        token=auth.token,
    )
    await ensure_site_tenant(pb, existing["site_id"], auth)

    updates: Dict[str, Any] = {}
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
        token=auth.token,
        user_id=auth.record["id"],
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
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    validate_id(property_id, "property_id")
    existing = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'property_id="{property_id}" && {SOFT_DELETE_FILTER}',
        token=auth.token,
    )
    await ensure_site_tenant(pb, existing["site_id"], auth)

    service = PropertyService()
    await service.soft_delete_property(
        pb=pb,
        token=auth.token,
        user_id=auth.record["id"],
        record=existing,
    )
    return Response(status_code=204)
