from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.application.services.public_submission_service import create_booking

SITE = {
    "config": {"public_submissions": {"enabled": True, "types": ["booking_submission"]}}
}


def _service(*fields):
    return {"groups": [{"key": "booking", "fields": list(fields)}]}


def _pb(service):
    pb = AsyncMock()
    pb.find_one_by_filter.side_effect = [SITE, service]
    pb.create_record.return_value = {"property_id": "submission", "site_id": "site"}
    return pb


BOOKING_FIELDS = [
    {"key": key, "label": key, "type": "text", "required": True}
    for key in ("customer_name", "customer_email", "date", "start_time", "end_time")
]


def _booking_values(**overrides):
    values = {
        "customer_name": "Guest",
        "customer_email": "guest@example.com",
        "date": "2026-10-26",
        "start_time": "10:00",
        "end_time": "11:00",
        **overrides,
    }
    return [{"key": k, "value": v} for k, v in values.items()]


@pytest.mark.parametrize(
    "field,value",
    [
        ({"key": "phone", "label": "Phone", "type": "text", "required": True}, ""),
        ({"key": "phone", "label": "Phone", "type": "text", "required": True}, "   "),
        (
            {
                "key": "services",
                "label": "Services",
                "type": "multi_select",
                "required": True,
                "options": ["A", "B"],
            },
            [],
        ),
    ],
)
async def test_blank_required_value_is_rejected(field, value):
    pb = _pb(_service(field))
    with pytest.raises(HTTPException) as exc:
        await create_booking(
            pb,
            "site",
            {
                "name": "Guest",
                "fields": [{"key": field["key"], "value": value}],
                "metadata": {"service_id": "svc"},
            },
        )
    assert exc.value.status_code == 400
    assert field["key"] in str(exc.value.detail)
    pb.create_record.assert_not_awaited()


async def test_filled_required_value_is_accepted():
    phone = {"key": "phone", "label": "Phone", "type": "text", "required": True}
    pb = _pb(_service(phone, *BOOKING_FIELDS))
    pb.list_records.return_value = {"items": [], "totalItems": 0}
    with patch(
        "app.application.services.transactional_service.TransactionalService._booking_slot",
        new_callable=AsyncMock,
    ):
        await create_booking(
            pb,
            "site",
            {
                "name": "Guest",
                "fields": [{"key": "phone", "value": "0901234567"}, *_booking_values()],
                "metadata": {"service_id": "svc"},
            },
        )
    pb.create_record.assert_awaited()


async def test_submission_that_cannot_become_a_booking_is_rejected_before_persisting():
    fields = [f for f in BOOKING_FIELDS if f["key"] != "end_time"]
    pb = _pb(_service(*fields))
    pb.list_records.return_value = {"items": [], "totalItems": 0}
    with pytest.raises(HTTPException) as exc:
        await create_booking(
            pb,
            "site",
            {
                "name": "Guest",
                "fields": [v for v in _booking_values() if v["key"] != "end_time"],
                "metadata": {"service_id": "svc"},
            },
        )
    assert exc.value.status_code == 422
    assert "end_time" in str(exc.value.detail)
    pb.create_record.assert_not_awaited()


async def test_full_slot_is_rejected_before_persisting():
    pb = _pb(_service(*BOOKING_FIELDS))
    pb.list_records.return_value = {"items": [], "totalItems": 0}
    with (
        patch(
            "app.application.services.transactional_service.TransactionalService._booking_slot",
            new_callable=AsyncMock,
            side_effect=HTTPException(409, "Slot unavailable"),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await create_booking(
            pb,
            "site",
            {
                "name": "Guest",
                "fields": _booking_values(),
                "metadata": {"service_id": "svc"},
            },
        )
    assert exc.value.status_code == 409
    pb.create_record.assert_not_awaited()


async def test_complete_submission_creates_submission_and_booking():
    pb = _pb(_service(*BOOKING_FIELDS))
    pb.find_one_by_filter.side_effect = [SITE, _service(*BOOKING_FIELDS), SITE, SITE]
    pb.list_records.return_value = {"items": [], "totalItems": 0}
    pb.create_record.return_value = {
        "property_id": "submission",
        "site_id": "site",
        "type": "booking_submission",
        "metadata": {"service_id": "svc"},
        "fields": _booking_values(),
    }
    with patch(
        "app.application.services.transactional_service.TransactionalService._booking_slot",
        new_callable=AsyncMock,
    ):
        await create_booking(
            pb,
            "site",
            {
                "name": "Guest",
                "fields": _booking_values(),
                "metadata": {"service_id": "svc"},
            },
        )
    collections = [
        c.args[0] if c.args else c.kwargs.get("collection")
        for c in pb.create_record.await_args_list
    ]
    assert "bookings" in collections
