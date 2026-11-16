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
from app.infrastructure.validation.field_validator import (
    is_vietnamese_phone,
    validate_fields,
)

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


PHONE_ERROR = "Invalid phone number: use 0xxxxxxxxx or +84xxxxxxxxx"
PHONE_KEYS = ("customer_phone", "phone")


def require_vietnamese_phone(value: Any) -> None:
    """A phone is optional, but a given one must be a Vietnamese number."""
    if _is_blank(value):
        return
    if not isinstance(value, str) or not is_vietnamese_phone(value):
        raise HTTPException(status_code=422, detail=PHONE_ERROR)


async def _require_accepting(
    pb: PocketBaseClient, site_id: str, submission_type: str
) -> None:
    """The site owner opts in to each public submission type."""
    site = await pb.find_one_by_filter(
        "sites", f'site_id="{sanitize_filter_value(site_id)}"'
    )
    assert_site_active(site)
    policy = (site.get("config") or {}).get("public_submissions") or {}
    if policy.get("enabled") is not True or submission_type not in policy.get(
        "types", []
    ):
        raise HTTPException(status_code=404, detail="Submissions unavailable")


def _merge_values(
    schema: list[dict[str, Any]], supplied: list[dict[str, Any]], kind: str
) -> list[dict[str, Any]]:
    """Copy submitted values onto the server's field schema.

    Validation constraints come from the server, never the submitter.
    """
    values = {field["key"]: field.get("value") for field in supplied}
    if len(values) != len(supplied) or set(values) - {field["key"] for field in schema}:
        raise HTTPException(
            status_code=422, detail=f"Unknown or duplicate {kind} fields"
        )
    if len(json.dumps(values).encode()) > 16384:
        raise HTTPException(
            status_code=413, detail=f"{kind.capitalize()} fields too large"
        )
    return [{**field, "value": values.get(field["key"])} for field in schema]


async def create_booking(
    pb: PocketBaseClient, site_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    async with operation_lock(f"site:{site_id}"):
        await _require_accepting(pb, site_id, "booking_submission")
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
        fields = _merge_values(schema, data["fields"], "booking")
        values = {field["key"]: field["value"] for field in fields}
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
        for key in PHONE_KEYS:
            require_vietnamese_phone(values.get(key))
        # Refuse what can never become a booking, before anything is stored: a 201
        # here used to leave the guest believing they had booked when no booking existed.
        submission_provider_id = (
            data.get("provider_id")
            or (data.get("metadata") or {}).get("provider_id")
            or values.get("provider_id")
            or values.get("provider")
        )
        booking, missing = structured_booking(
            service_id, fields, provider_id=submission_provider_id
        )
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Booking cannot be scheduled, missing: {', '.join(missing)}",
            )
        await TransactionalService()._booking_slot(
            pb, pb._static_token, site_id, booking
        )
        slug_candidate = data.get("slug") or service_id
        try:
            await PropertyService()._check_slug_unique(
                pb, pb._static_token, site_id, slug_candidate
            )
        except HTTPException:
            slug_candidate = f"{service_id}-{uuid.uuid4().hex[:6]}"

        submission_metadata = {"service_id": service_id, "source": "website"}
        if booking.get("provider_id"):
            submission_metadata["provider_id"] = booking["provider_id"]

        created = await PropertyService().create_property(
            pb=pb,
            token=pb._static_token,
            user_id="",
            site_id=site_id,
            data={
                "property_id": data.get("property_id") or f"booking_{uuid.uuid4().hex}",
                "type": "booking_submission",
                "name": data["name"],
                "slug": slug_candidate,
                # Published means submitted, not approved or confirmed.
                "status": "published",
                "fields": fields,
                "groups": [],
                "metadata": submission_metadata,
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


ENQUIRY_FIELDS: list[dict[str, Any]] = [
    {"key": "customer_name", "label": "Name", "type": "text", "required": True},
    {"key": "customer_email", "label": "Email", "type": "email", "required": True},
    {"key": "customer_phone", "label": "Phone", "type": "text"},
    {"key": "message", "label": "Message", "type": "textarea"},
]
"""Server-owned enquiry schema: the submitter supplies values, never constraints."""


async def create_enquiry(
    pb: PocketBaseClient, site_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    """Store a website enquiry (viewing request, free trial, contact).

    Unlike a booking there is no service or capacity to check: the record is
    the whole outcome, and the owner reads it from the properties listing.
    """
    await _require_accepting(pb, site_id, "enquiry_submission")
    fields = _merge_values(ENQUIRY_FIELDS, data["fields"], "enquiry")
    blank = [
        field["key"]
        for field in fields
        if field.get("required") and _is_blank(field["value"])
    ]
    if blank:
        raise HTTPException(
            status_code=422,
            detail=f"Required enquiry fields missing: {', '.join(blank)}",
        )
    errors = validate_fields(fields)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    require_vietnamese_phone(
        next(f["value"] for f in fields if f["key"] == "customer_phone")
    )

    metadata = {
        key: value
        for key, value in (data.get("metadata") or {}).items()
        if value is not None
    }
    property_id = f"enquiry_{uuid.uuid4().hex}"
    return await PropertyService().create_property(
        pb=pb,
        token=pb._static_token,
        user_id="",
        site_id=site_id,
        data={
            "property_id": property_id,
            "type": "enquiry_submission",
            "name": data["name"],
            # Random, so the slug check cannot collide and no site lock is needed.
            "slug": property_id,
            # Published means submitted, never trusted from the caller.
            "status": "published",
            "fields": fields,
            "groups": [],
            "metadata": {**metadata, "source": "website"},
        },
    )
