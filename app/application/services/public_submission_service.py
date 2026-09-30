import json
import uuid
from typing import Any

from fastapi import HTTPException

from app.application.services.property_service import PropertyService
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value


async def create_booking(
    pb: PocketBaseClient, site_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    site = await pb.find_one_by_filter(
        "sites", f'site_id="{sanitize_filter_value(site_id)}"'
    )
    policy = (site.get("config") or {}).get("public_submissions") or {}
    if policy.get("enabled") is not True or "booking_submission" not in policy.get(
        "types", []
    ):
        raise HTTPException(status_code=404, detail="Submissions unavailable")
    service_id = data["metadata"]["service_id"]
    service = await pb.find_one_by_filter(
        "properties",
        f'site_id="{sanitize_filter_value(site_id)}" && property_id="{sanitize_filter_value(service_id)}" && type="spa_service" && status="published" && deleted_at=""',
    )
    schema = next(
        (
            group.get("fields", [])
            for group in service.get("groups", [])
            if group.get("key") == "booking"
        ),
        [],
    )
    if not schema:
        raise HTTPException(status_code=404, detail="Booking unavailable")
    supplied = data["fields"]
    values = {field["key"]: field.get("value") for field in supplied}
    if len(values) != len(supplied) or set(values) - {field["key"] for field in schema}:
        raise HTTPException(
            status_code=422, detail="Unknown or duplicate booking fields"
        )
    if len(json.dumps(values).encode()) > 16384:
        raise HTTPException(status_code=413, detail="Booking fields too large")
    # Validation constraints come from the published service, never the submitter.
    fields = [{**field, "value": values.get(field["key"])} for field in schema]
    return await PropertyService().create_property(
        pb=pb,
        token=pb._static_token,
        user_id="",
        site_id=site_id,
        data={
            "property_id": data.get("property_id") or f"booking_{uuid.uuid4().hex}",
            "type": "booking_submission",
            "name": data["name"],
            # Published means submitted, not approved or confirmed.
            "status": "published",
            "fields": fields,
            "groups": [],
            "metadata": {"service_id": service_id, "source": "website"},
        },
    )
