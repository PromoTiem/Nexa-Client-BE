import json
import uuid
from typing import Any

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.application.services.legacy_booking_service import (
    convert_submission,
    structured_booking,
)
from app.application.services.property_service import PropertyService
from app.application.services.transactional_service import TransactionalService
from app.infrastructure.logging import get_logger
from app.infrastructure.operation_lock import operation_lock
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value

logger = get_logger("public_submission_service")


def _is_blank(value: Any) -> bool:
    """A guest leaving a required input empty sends "" or [], not null."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


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
        blank = [
            field["key"]
            for field in fields
            if field.get("required") and _is_blank(field["value"])
        ]
        if blank:
            raise HTTPException(
                status_code=400,
                detail=f"Required booking fields missing: {', '.join(blank)}",
            )
        # Refuse what can never become a booking, before anything is stored: a 201
        # here used to leave the guest believing they had booked when no booking existed.
        booking, missing = structured_booking(service_id, fields)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Booking cannot be scheduled, missing: {', '.join(missing)}",
            )
        await TransactionalService()._booking_slot(
            pb, pb._static_token, site_id, booking
        )
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

        try:
            outcome = await convert_submission(
                pb, pb._static_token, created, source="website", apply=True
            )
            logger.info(
                "booking conversion",
                extra={"source_id": created.get("property_id"), "outcome": outcome},
            )
        except Exception as exc:
            logger.error(
                "booking conversion failed after the slot check passed",
                extra={
                    "source_id": created.get("property_id"),
                    "error_type": type(exc).__name__,
                },
            )
        return created
