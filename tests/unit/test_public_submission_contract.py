from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.application.services.public_submission_service import (
    PHONE_ERROR,
    create_booking,
    create_enquiry,
)
from app.config import Settings, get_settings
from app.infrastructure.rate_limits import get_limiter
from app.interface.dependencies import (
    get_pocketbase_client,
    get_static_pocketbase_client,
    get_tenant_context,
)
from app.interface.exception_handlers import register_exception_handlers
from app.interface.routes.property import public_property_router
from app.interface.routes.property import router as property_router
from tests.fake_pocketbase import FakePocketBase
from tests.unit.test_retained_consumer import context

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


# ---------------------------------------------------------------------------
# Phone validation on bookings
# ---------------------------------------------------------------------------

PHONE_FIELD = {"key": "customer_phone", "label": "Phone", "type": "text"}


def _phone_booking_pb(key: str):
    pb = _pb(_service({**PHONE_FIELD, "key": key}, *BOOKING_FIELDS))
    pb.list_records.return_value = {"items": [], "totalItems": 0}
    return pb


async def _book_with_phone(pb, key: str, phone):
    with patch(
        "app.application.services.transactional_service.TransactionalService._booking_slot",
        new_callable=AsyncMock,
    ):
        await create_booking(
            pb,
            "site",
            {
                "name": "Guest",
                "fields": [{"key": key, "value": phone}, *_booking_values()],
                "metadata": {"service_id": "svc"},
            },
        )


@pytest.mark.parametrize("key", ["customer_phone", "phone"])
@pytest.mark.parametrize(
    "phone", ["0901234567", "+84901234567", "+84 901 234 567", "090.123-4567", "", None]
)
async def test_booking_accepts_vietnamese_or_absent_phone(key, phone):
    pb = _phone_booking_pb(key)
    await _book_with_phone(pb, key, phone)
    pb.create_record.assert_awaited()


@pytest.mark.parametrize("key", ["customer_phone", "phone"])
@pytest.mark.parametrize(
    "phone", ["abc", "12345", "+8490123456", "09012345678", 901234567]
)
async def test_booking_rejects_invalid_phone_before_persisting(key, phone):
    pb = _phone_booking_pb(key)
    with pytest.raises(HTTPException) as exc:
        await _book_with_phone(pb, key, phone)
    assert exc.value.status_code == 422
    assert exc.value.detail == PHONE_ERROR
    pb.create_record.assert_not_awaited()


# ---------------------------------------------------------------------------
# enquiry_submission: estate "Book a viewing", SaaS "Start free trial"
# ---------------------------------------------------------------------------

ENQUIRY_SITE = "site_estate_1"


def _site(types, enabled=True, site_id=ENQUIRY_SITE):
    return {
        "id": f"rec_{site_id}",
        "site_id": site_id,
        "tenant_id": "tenant_rec",
        "config": {"public_submissions": {"enabled": enabled, "types": types}},
    }


def _enquiry_pb(types=("enquiry_submission",), enabled=True):
    return FakePocketBase(
        sites=[_site(list(types), enabled)],
        tenants=[{"id": "tenant_rec", "tenant_id": "tenant"}],
        properties=[],
    )


def _enquiry_app(pb):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(public_property_router, prefix="/public")
    app.include_router(property_router)
    app.dependency_overrides[get_static_pocketbase_client] = lambda: pb
    app.dependency_overrides[get_pocketbase_client] = lambda: pb
    app.dependency_overrides[get_tenant_context] = context
    app.dependency_overrides[get_settings] = lambda: Settings(
        rate_limit_storage_uri="memory://"
    )
    get_limiter("memory://").storage.reset()
    return app


def _enquiry_body(**overrides):
    values = {
        "customer_name": "Tran Thi B",
        "customer_email": "b@example.com",
        "customer_phone": "+84 912 345 678",
        "message": "Saturday morning works.",
    }
    values.update(overrides.pop("values", {}))
    body = {
        "type": "enquiry_submission",
        "name": "Viewing: Villa 12",
        "status": "published",
        "fields": [
            {"key": k, "label": k, "type": "text", "value": v}
            for k, v in values.items()
            if v is not ...
        ],
        "metadata": {
            "source": "website",
            "topic": "viewing",
            "reference_id": "villa-12",
            "reference_title": "Villa 12, District 2",
        },
    }
    body.update(overrides)
    return body


async def _post(app, body, site_id=ENQUIRY_SITE):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(f"/public/sites/{site_id}/properties", json=body)


async def test_enquiry_is_stored_when_the_site_allows_it():
    pb = _enquiry_pb()

    response = await _post(_enquiry_app(pb), _enquiry_body())

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["type"] == "enquiry_submission"
    assert data["status"] == "published"
    assert data["site_id"] == ENQUIRY_SITE
    assert data["property_id"].startswith("enquiry_")
    assert data["metadata"] == {
        "source": "website",
        "topic": "viewing",
        "reference_id": "villa-12",
        "reference_title": "Villa 12, District 2",
    }
    values = {f["key"]: f["value"] for f in data["fields"]}
    assert values == {
        "customer_name": "Tran Thi B",
        "customer_email": "b@example.com",
        "customer_phone": "+84 912 345 678",
        "message": "Saturday morning works.",
    }
    # Field constraints come from the server, not from what the submitter declared.
    types = {f["key"]: f["type"] for f in data["fields"]}
    assert types["customer_email"] == "email"
    assert [c for c, _ in pb.created] == ["properties"]
    assert not any(c == "bookings" for c, _ in pb.created)


async def test_trial_enquiry_with_only_required_fields():
    pb = _enquiry_pb()
    body = _enquiry_body(values={"customer_phone": ..., "message": ...})
    body["metadata"] = {"source": "website", "topic": "trial"}

    response = await _post(_enquiry_app(pb), body)

    assert response.status_code == 201, response.text
    assert response.json()["metadata"] == {"source": "website", "topic": "trial"}


@pytest.mark.parametrize(
    "types,enabled",
    [(("booking_submission",), True), (("enquiry_submission",), False), ((), True)],
)
async def test_enquiry_is_unavailable_unless_the_site_allows_it(types, enabled):
    pb = _enquiry_pb(types, enabled)

    response = await _post(_enquiry_app(pb), _enquiry_body())

    assert response.status_code == 404
    assert response.json()["detail"] == "Submissions unavailable"
    assert pb.created == []


@pytest.mark.parametrize(
    "values,expected",
    [
        ({"customer_email": ...}, "Required enquiry fields missing: customer_email"),
        ({"customer_email": ""}, "Required enquiry fields missing: customer_email"),
        ({"customer_email": "   "}, "Required enquiry fields missing: customer_email"),
        ({"customer_name": ...}, "Required enquiry fields missing: customer_name"),
        ({"customer_email": "not-an-email"}, "'customer_email': invalid email format"),
        ({"customer_phone": "abc"}, PHONE_ERROR),
        ({"customer_phone": "12345"}, PHONE_ERROR),
        ({"company": "Acme"}, "Unknown or duplicate enquiry fields"),
    ],
)
async def test_invalid_enquiry_fields_are_rejected(values, expected):
    pb = _enquiry_pb()

    response = await _post(_enquiry_app(pb), _enquiry_body(values=values))

    assert response.status_code == 422, response.text
    assert expected in response.json()["detail"]
    assert pb.created == []


async def test_duplicate_enquiry_field_is_rejected():
    pb = _enquiry_pb()
    body = _enquiry_body()
    body["fields"].append(
        {"key": "customer_email", "label": "x", "type": "text", "value": "c@d.io"}
    )

    response = await _post(_enquiry_app(pb), body)

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown or duplicate enquiry fields"
    assert pb.created == []


@pytest.mark.parametrize(
    "override",
    [
        {"status": "draft"},
        {"metadata": {"source": "website", "topic": "pricing"}},
        {"metadata": {"source": "email", "topic": "viewing"}},
        {"metadata": {"source": "website", "topic": "viewing", "extra": 1}},
        {"metadata": {"source": "website", "topic": "viewing", "reference_id": "a b"}},
        {"property_id": "chosen_by_client"},
    ],
)
async def test_enquiry_envelope_is_strict(override):
    pb = _enquiry_pb()

    response = await _post(_enquiry_app(pb), _enquiry_body(**override))

    assert response.status_code == 422, response.text
    assert pb.created == []


async def test_server_sets_enquiry_status_even_if_the_caller_does_not():
    pb = _enquiry_pb()
    data = _enquiry_body()
    data["status"] = "draft"

    created = await create_enquiry(pb, ENQUIRY_SITE, data)

    assert created["status"] == "published"
    assert created["type"] == "enquiry_submission"


async def test_booking_without_type_still_routes_to_booking():
    pb = _enquiry_pb(types=("enquiry_submission",))
    body = {
        "name": "Guest",
        "fields": [
            {"key": "customer_name", "label": "n", "type": "text", "value": "G"}
        ],
        "metadata": {"service_id": "svc"},
    }

    response = await _post(_enquiry_app(pb), body)

    # Booking is not enabled on this site: the booking gate answers, not a union error.
    assert response.status_code == 404
    assert response.json()["detail"] == "Submissions unavailable"


async def test_owner_lists_enquiries_through_the_authenticated_listing():
    pb = _enquiry_pb()
    app = _enquiry_app(pb)
    assert (await _post(app, _enquiry_body())).status_code == 201

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        everything = await client.get(f"/sites/{ENQUIRY_SITE}/properties")
        only = await client.get(
            f"/sites/{ENQUIRY_SITE}/properties", params={"type": "enquiry_submission"}
        )

    assert everything.status_code == 200, everything.text
    assert [p["type"] for p in everything.json()["items"]] == ["enquiry_submission"]
    assert only.json()["total"] == 1
