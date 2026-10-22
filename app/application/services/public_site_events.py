"""Anonymous visitor actions on a published site: analytics events and newsletter sign-ups."""

import hashlib
import re
from typing import Any

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.application.services.property_service import PropertyService
from app.infrastructure.analytics.collector import AnalyticsCollector
from app.infrastructure.operation_lock import operation_lock
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value

NEWSLETTER_TYPE = "newsletter_subscription"
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


async def _active_site(pb: PocketBaseClient, site_id: str) -> dict[str, Any]:
    site = await pb.find_one_by_filter(
        "sites", f'site_id="{sanitize_filter_value(site_id)}"'
    )
    assert_site_active(site)
    return site


async def track_public_event(
    pb: PocketBaseClient, collector: AnalyticsCollector, event
) -> str:
    site = await _active_site(pb, event.site_id)
    if event.property_id:
        # Raises 404 when the property is not a published property of this site.
        await pb.find_one_by_filter(
            "properties",
            f'site_id="{sanitize_filter_value(event.site_id)}" && property_id="{sanitize_filter_value(event.property_id)}" && status="published" && deleted_at=""',
        )
    return await collector.record_event(
        event_type=event.event_type,
        site_id=event.site_id,
        property_id=event.property_id,
        tenant_id=site.get("tenant_id") or "",
        session_id=event.session_id,
        metadata=event.metadata,
    )


async def subscribe_newsletter(pb: PocketBaseClient, site_id: str, email: str) -> None:
    """Store one subscription per site and address; repeats succeed without revealing that."""
    address = (email or "").strip().lower()
    if not _EMAIL_RE.match(address):
        raise HTTPException(status_code=400, detail="Invalid email address")
    async with operation_lock(f"site:{site_id}"):
        site = await _active_site(pb, site_id)
        policy = (site.get("config") or {}).get("public_submissions") or {}
        if policy.get("enabled") is not True or NEWSLETTER_TYPE not in policy.get(
            "types", []
        ):
            raise HTTPException(status_code=404, detail="Submissions unavailable")
        digest = hashlib.sha256(f"{site_id}:{address}".encode()).hexdigest()[:32]
        property_id = f"sub_{digest}"
        existing = await pb.list_records(
            "properties",
            filter=f'site_id="{sanitize_filter_value(site_id)}" && property_id="{property_id}"',
            per_page=1,
        )
        if existing.get("items"):
            return
        await PropertyService().create_property(
            pb=pb,
            token=pb._static_token,
            user_id="",
            site_id=site_id,
            data={
                "property_id": property_id,
                "type": NEWSLETTER_TYPE,
                "name": "Newsletter subscriber",
                "status": "published",
                "fields": [
                    {
                        "key": "email",
                        "label": "Email",
                        "type": "email",
                        "required": True,
                        "value": address,
                    }
                ],
                "groups": [],
                "metadata": {"source": "website"},
            },
        )
