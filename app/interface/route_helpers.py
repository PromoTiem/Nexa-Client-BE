import re
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException

from app.application.access import enforce_site_access
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import (
    sanitize_filter_value as sanitize_filter_value,
)
from app.interface.auth_models import AuthContext

# ----- ID validation -------------------------------------------------- #

ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def validate_id(value: str, name: str = "id") -> None:
    if not ID_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {name} format")


# ----- filter sanitization -------------------------------------------------- #

# ----- sort validation -------------------------------------------------- #

_SORT_FIELD_RE = re.compile(r"^-?[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_sort(value: str, allowed_fields: list[str] | None = None) -> str:
    """Validate sort parameter to prevent injection.

    Args:
        value: The sort string to validate (e.g., "-created_at" or "name")
        allowed_fields: Optional list of allowed field names. If provided,
                       the sort field must be in this list.

    Returns:
        The validated sort string.

    Raises:
        HTTPException: 400 if the sort format is invalid.
    """
    parts = value.split(",")
    validated_parts = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        field = part.lstrip("-")

        if not _SORT_FIELD_RE.match(part):
            raise HTTPException(status_code=400, detail=f"Invalid sort format: {part}")

        if allowed_fields and field not in allowed_fields:
            raise HTTPException(status_code=400, detail=f"Invalid sort field: {field}")

        validated_parts.append(part)

    return ",".join(validated_parts) if validated_parts else "-created_at"


# ----- filter building -------------------------------------------------- #


def build_filter(parts: list[str]) -> str | None:
    """Join filter parts with ``&&`` into a single PocketBase filter expression."""
    return " && ".join(parts) if parts else None


# ----- auth / tenant helpers ------------------------------------------- #


def auth_tenant(auth: AuthContext) -> str | None:
    return auth.record.get("tenant_id")


def ensure_tenant_owns(record: dict[str, Any], auth: AuthContext) -> None:
    tenant = auth_tenant(auth)
    if tenant and record.get("tenant_id") != tenant:
        raise HTTPException(status_code=404, detail="Record not found")


# ----- PocketBase ID resolution ---------------------------------------- #


async def ensure_site_tenant(
    pb: PocketBaseClient,
    site_id: str,
    auth: AuthContext,
) -> None:
    await enforce_site_access(pb, site_id, auth)


async def ensure_file_tenant(
    pb: PocketBaseClient,
    record: dict[str, Any],
    auth: AuthContext,
) -> None:
    """Verify that a file record's parent site belongs to the caller's tenant.

    Passes silently for admin users (no tenant_id on auth record).
    Raises 404 if the file's site belongs to a different tenant.
    """
    tenant = auth_tenant(auth)
    if not tenant:
        return
    site_id = record.get("site_id")
    if not site_id:
        raise HTTPException(status_code=404, detail="File not found")
    await ensure_site_tenant(pb, site_id, auth)


async def tenant_record_id(
    pb: PocketBaseClient,
    token: str,
    tenant_id: str | None,
) -> str:
    """Resolve the public business ``tenant_id`` to its internal PocketBase record id.

    Raises 403 when no tenant is set, so tenant-scoped routes fail closed rather
    than silently dropping the isolation boundary.
    """
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Client access requires tenant_id")
    return await public_id_to_record_id(pb, "tenants", "tenant_id", tenant_id, token)


async def tenant_filter(
    pb: PocketBaseClient,
    token: str,
    tenant_id: str | None,
) -> str:
    """Build a PocketBase filter clause scoping records to the caller's tenant.

    Content collections (templates/styles/blocks/pages/sections) store
    ``tenant_id`` as the **internal PocketBase record id**, so the public
    business ``tenant_id`` is resolved first via ``tenant_record_id``.

    Fails closed: when no tenant is set the caller is not allowed an unscoped
    view, so a 403 is raised instead of returning an unrestricted filter.
    """
    record_id = await tenant_record_id(pb, token, tenant_id)
    return f'tenant_id="{sanitize_filter_value(record_id)}"'


def combine_filter(base: str, tenant_clause: str | None) -> str:
    """AND a base filter expression with a tenant clause, parenthesizing the base.

    Used by tenant-scoped GET handlers so the tenant condition cannot be escaped by
    operator precedence in the base expression.
    """
    if tenant_clause:
        return f"({base}) && {tenant_clause}"
    return base


async def public_id_to_record_id(
    pb: PocketBaseClient,
    collection: str,
    public_field: str,
    public_id: str,
    token: str,
) -> str:
    record = await pb.find_one_by_filter(
        collection=collection,
        filter_expr=f'{public_field}="{sanitize_filter_value(public_id)}"',
        token=token,
    )
    return record["id"]


async def record_id_to_public_id(
    pb: PocketBaseClient,
    collection: str,
    public_field: str,
    record_id: str | None,
    token: str,
) -> str | None:
    if not record_id:
        return None
    try:
        record = await pb.find_one_by_filter(
            collection=collection,
            filter_expr=f'id="{sanitize_filter_value(record_id)}"',
            token=token,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return None
    return record.get(public_field)


# ----- record field mapping -------------------------------------------- #


async def map_site_record(
    record: dict[str, Any],
    token: str,
    pb: PocketBaseClient,
    fields: Sequence[str] = ("tenant_id",),
) -> dict[str, Any]:
    """Resolve internal PocketBase IDs to public IDs for the given fields."""
    mapped = dict(record)
    field_collection_map = {
        "tenant_id": ("tenants", "tenant_id"),
        "template_id": ("templates", "template_id"),
        "domain_id": ("domains", "domain_id"),
    }
    for field in fields:
        collection, public_field = field_collection_map[field]
        mapped[field] = await record_id_to_public_id(
            pb, collection, public_field, record.get(field), token
        )
    return mapped


async def enforce_property_site(
    pb: PocketBaseClient, site_id: str, property_id: str, token: str
) -> None:
    validate_id(property_id, "property_id")
    await pb.find_one_by_filter(
        collection="properties",
        filter_expr=f'site_id="{sanitize_filter_value(site_id)}" && property_id="{sanitize_filter_value(property_id)}" && deleted_at=""',
        token=token,
    )


async def tenant_resource_id(
    pb: PocketBaseClient,
    collection: str,
    field: str,
    value: str,
    token: str,
    tenant_id: str,
) -> str:
    validate_id(value, field)
    clause = await tenant_filter(pb, token, tenant_id)
    record = await pb.find_one_by_filter(
        collection=collection,
        filter_expr=combine_filter(f'{field}="{sanitize_filter_value(value)}"', clause),
        token=token,
    )
    return record["id"]


def resolve_page_size(limit: int | None, per_page: int | None) -> int:
    if limit is not None and per_page is not None and limit != per_page:
        raise HTTPException(status_code=422, detail="limit and per_page must agree")
    return per_page if per_page is not None else (limit if limit is not None else 20)
