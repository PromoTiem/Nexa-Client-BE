"""Tenant authorization shared by application workflows and HTTP dependencies."""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value

ACTIVE_SITE_FILTER = '(config._nexa_lifecycle.deleted_at = null || config._nexa_lifecycle.deleted_at = "")'


def assert_site_active(site: dict[str, Any]) -> None:
    config = site.get("config")
    lifecycle = config.get("_nexa_lifecycle") if isinstance(config, dict) else None
    if isinstance(lifecycle, dict) and lifecycle.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Site not found")


def client_site_config(
    incoming: dict[str, Any] | None, existing: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Never let client config replacement erase or forge server lifecycle state."""
    if incoming is not None and "_nexa_lifecycle" in incoming:
        raise HTTPException(status_code=422, detail="Site lifecycle is server-owned")
    if existing and "_nexa_lifecycle" in existing:
        return {**(incoming or {}), "_nexa_lifecycle": existing["_nexa_lifecycle"]}
    return incoming


@dataclass
class AuthContext:
    token: str
    record: dict[str, Any]


async def enforce_site_access(
    pb: PocketBaseClient, site_id: str, auth: AuthContext
) -> dict[str, Any]:
    tenant_id = auth.record.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Client access requires tenant_id")
    site = await pb.find_one_by_filter(
        collection="sites",
        filter_expr=f'site_id="{sanitize_filter_value(site_id)}"',
        token=auth.token,
    )
    assert_site_active(site)
    relation = site.get("tenant_id")
    if not relation:
        raise HTTPException(status_code=404, detail="Site not found")
    tenant = await pb.find_one_by_filter(
        collection="tenants",
        filter_expr=f'id="{sanitize_filter_value(relation)}"',
        token=auth.token,
    )
    if tenant.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Site not found")
    return site
