import re
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException

from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.auth_models import AuthContext

# ----- ID validation -------------------------------------------------- #

ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def validate_id(value: str, name: str = "id") -> None:
    if not ID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {name} format")


# ----- filter sanitization -------------------------------------------------- #

# Characters that could be used for PocketBase filter injection
_FILTER_UNSAFE_RE = re.compile(r'["\\]')


def sanitize_filter_value(value: str) -> str:
    """Escape double quotes and backslashes in filter values to prevent injection."""
    return _FILTER_UNSAFE_RE.sub(lambda m: "\\" + m.group(0), value)


# ----- sort validation -------------------------------------------------- #

# Valid sort field names (alphanumeric + underscore only)
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

        # Extract field name (remove leading - for descending)
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
    """Verify that the site with the given site_id belongs to the caller's tenant.

    Passes silently for admin users (no tenant_id on auth record).
    Raises 404 if the site exists but belongs to a different tenant.
    """
    tenant = auth_tenant(auth)
    if not tenant:
        return
    site = await pb.find_one_by_filter(
        collection="sites",
        filter_expr=f'site_id="{site_id}"',
        token=auth.token,
    )
    site_tenant_public_id = await record_id_to_public_id(
        pb, "tenants", "tenant_id", site.get("tenant_id"), auth.token
    )
    if site_tenant_public_id != tenant:
        raise HTTPException(status_code=404, detail="Site not found")


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
        return
    await ensure_site_tenant(pb, site_id, auth)


async def public_id_to_record_id(
    pb: PocketBaseClient,
    collection: str,
    public_field: str,
    public_id: str,
    token: str,
) -> str:
    record = await pb.find_one_by_filter(
        collection=collection,
        filter_expr=f'{public_field}="{public_id}"',
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
            filter_expr=f'id="{record_id}"',
            token=token,
        )
    except HTTPException:
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
