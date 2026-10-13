import json
import uuid
from typing import Any

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.application.services.property_service import PropertyService
from app.infrastructure.logging import get_logger
from app.infrastructure.operation_lock import operation_lock
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value

logger = get_logger("public_submission_service")


async def create_booking(
    pb: PocketBaseClient, site_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    async with operation_lock(f"site:{site_id}"):
        site = await pb.find_one_by_filter(
            "sites", f'site_id="{sanitize_filter_value(site_id)}"'
        )
        assert_site_active(site)
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
        if len(values) != len(supplied) or set(values) - {
            field["key"] for field in schema
        }:
            raise HTTPException(
                status_code=422, detail="Unknown or duplicate booking fields"
            )
        if len(json.dumps(values).encode()) > 16384:
            raise HTTPException(status_code=413, detail="Booking fields too large")
        # Validation constraints come from the published service, never the submitter.
        fields = [{**field, "value": values.get(field["key"])} for field in schema]
        created = await PropertyService().create_property(
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

        await _dual_write_booking(pb, created, values, service_id)
        return created


async def _dual_write_booking(
    pb: PocketBaseClient,
    submission: dict[str, Any],
    values: dict[str, Any],
    service_id: str,
) -> None:
    """Create a structured booking when the dynamic form has booking fields.

    Legacy property submissions remain the source of truth when a tenant's
    custom form does not provide all structured booking fields.
    """
    required = {
        "customer_name": values.get("customer_name") or values.get("name"),
        "customer_email": values.get("customer_email") or values.get("email"),
        "date": values.get("date"),
        "start_time": values.get("start_time"),
        "end_time": values.get("end_time"),
    }
    if any(value in (None, "") for value in required.values()):
        logger.info(
            "booking submission retained as legacy property",
            extra={
                "property_id": submission.get("property_id"),
                "service_id": service_id,
            },
        )
        return
    try:
        await pb.create_record(
            "bookings",
            {
                "booking_id": f"booking_{uuid.uuid4().hex}",
                "site_id": submission["site_id"],
                "property_id": service_id,
                **required,
                "customer_phone": values.get("customer_phone") or values.get("phone"),
                "status": "pending",
                "fields": submission.get("fields", []),
                "metadata": {
                    "source": "website",
                    "legacy_property_id": submission.get("property_id"),
                },
                "deleted_at": "",
            },
            token=pb._static_token,
        )
    except Exception as exc:
        logger.warning(
            "structured booking dual-write failed",
            extra={"property_id": submission.get("property_id"), "error": str(exc)},
        )
