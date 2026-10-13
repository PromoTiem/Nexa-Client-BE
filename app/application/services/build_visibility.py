"""Build visibility without superuser-only PocketBase collection joins."""

from fastapi import HTTPException

from app.application.access import ACTIVE_SITE_FILTER
from app.infrastructure.pocketbase.filters import sanitize_filter_value

# Bound the GET filter size; callers can narrow large tenants to one site.
MAX_VISIBLE_SITES = 200


async def visible_site_filter(pb, token: str, tenant_id: str, site_id: str | None):
    tenant = sanitize_filter_value(tenant_id)
    predicate = f'tenant_id="{tenant}" && {ACTIVE_SITE_FILTER}'
    if site_id:
        predicate += f' && site_id="{sanitize_filter_value(site_id)}"'
    result = await pb.list_records(
        collection="sites",
        token=token,
        filter=predicate,
        page=1,
        per_page=MAX_VISIBLE_SITES + 1,
    )
    rows = result.get("items", [])
    if (
        result.get("totalItems", len(rows)) > MAX_VISIBLE_SITES
        or len(rows) > MAX_VISIBLE_SITES
    ):
        raise HTTPException(
            422, "Specify site_id when listing builds for more than 200 sites"
        )
    ids = list(dict.fromkeys(row["site_id"] for row in rows))
    if not ids:
        return None
    expression = (
        "("
        + " || ".join(f'site_id="{sanitize_filter_value(value)}"' for value in ids)
        + ")"
    )
    if len(expression.encode()) > 12000:
        raise HTTPException(422, "Specify site_id to narrow the build query")
    return expression
