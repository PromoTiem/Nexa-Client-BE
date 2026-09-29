"""Tenant authorization shared by application workflows and HTTP dependencies."""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value


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
