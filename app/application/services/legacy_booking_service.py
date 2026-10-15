"""Retry-safe conversion; caller holds the site lock, source remains untouched."""

from hashlib import sha256

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.application.services.transactional_service import (
    TransactionalService,
    filter_value,
)


async def convert_submission(pb, token, submission, *, source, apply=False):
    site_id, source_id = submission.get("site_id"), submission.get("property_id")
    if (
        not site_id
        or not source_id
        or submission.get("type") != "booking_submission"
        or submission.get("deleted_at")
    ):
        raise HTTPException(422, "Invalid legacy source")
    site = await pb.find_one_by_filter(
        "sites", f"site_id={filter_value(site_id)}", token=token
    )
    assert_site_active(site)
    found = await pb.list_records(
        "bookings",
        token=token,
        filter=f"metadata.legacy_property_id={filter_value(source_id)}",
        per_page=2,
    )
    matches = found.get("items", [])
    if len(matches) > 1 or found.get("totalItems", 0) > 1:
        raise HTTPException(409, "Duplicate legacy source")
    if matches:
        if matches[0].get("site_id") != site_id:
            raise HTTPException(409, "Foreign legacy source")
        return "existing"
    fields = submission.get("fields") or []
    values = {field.get("key"): field.get("value") for field in fields}
    data = {
        "property_id": (submission.get("metadata") or {}).get("service_id"),
        "customer_name": values.get("customer_name") or values.get("name"),
        "customer_email": values.get("customer_email") or values.get("email"),
        "date": values.get("date"),
        "start_time": values.get("start_time"),
        "end_time": values.get("end_time"),
    }
    if any(value in (None, "") for value in data.values()):
        return "incomplete"
    await TransactionalService()._booking_slot(pb, token, site_id, data)
    if not apply:
        return "would_convert"
    await pb.create_record(
        "bookings",
        {
            **data,
            "booking_id": "booking_"
            + sha256(f"{site_id}:{source_id}".encode()).hexdigest()[:32],
            "site_id": site_id,
            "status": "pending",
            "deleted_at": "",
            "fields": fields,
            "customer_phone": values.get("customer_phone") or values.get("phone"),
            "metadata": {"source": source, "legacy_property_id": source_id},
        },
        token=token,
    )
    return "converted"
