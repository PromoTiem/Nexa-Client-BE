from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.services.transactional_service import TransactionalService

MONDAY_DATE = "2026-10-19"
PROP_ID = "prop_spa_01"
SITE_ID = "site_01"


def make_service(slots, bookings, prop_type="spa_service", prop_status="published"):
    svc = TransactionalService()
    pb = AsyncMock()

    async def list_records_mock(collection, **kwargs):
        if collection == "availability":
            return {"items": slots, "totalPages": 1}
        if collection == "bookings":
            return {"items": bookings, "totalPages": 1}
        return {"items": [], "totalPages": 1}

    async def properties_mock(pb, token, site_id, property_ids):
        return {
            PROP_ID: {
                "property_id": PROP_ID,
                "type": prop_type,
                "status": prop_status,
                "name": "Luxury Massage",
            }
        }

    pb.list_records = AsyncMock(side_effect=list_records_mock)
    svc._properties = AsyncMock(side_effect=properties_mock)
    return svc, pb


@pytest.mark.asyncio
async def test_booking_with_explicit_provider_id_respects_provider_capacity():
    slots = [
        {
            "availability_id": "slot_p1",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "max_bookings": 1,
            "is_active": True,
            "provider_id": "provider_alice",
        }
    ]
    bookings = []
    svc, pb = make_service(slots, bookings)

    booking_data = {
        "property_id": PROP_ID,
        "date": MONDAY_DATE,
        "start_time": "10:00",
        "end_time": "11:00",
        "provider_id": "provider_alice",
    }
    await svc._booking_slot(pb, "token", SITE_ID, booking_data)


@pytest.mark.asyncio
async def test_concurrent_booking_for_same_provider_triggers_409_conflict():
    slots = [
        {
            "availability_id": "slot_p1",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "max_bookings": 1,
            "is_active": True,
            "provider_id": "provider_alice",
        }
    ]
    existing_bookings = [
        {
            "booking_id": "b_existing_alice",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "date": MONDAY_DATE,
            "start_time": "10:00",
            "end_time": "11:00",
            "status": "confirmed",
            "provider_id": "provider_alice",
        }
    ]
    svc, pb = make_service(slots, existing_bookings)

    booking_data = {
        "property_id": PROP_ID,
        "date": MONDAY_DATE,
        "start_time": "10:30",
        "end_time": "11:30",
        "provider_id": "provider_alice",
    }
    with pytest.raises(HTTPException) as exc_info:
        await svc._booking_slot(pb, "token", SITE_ID, booking_data)

    assert exc_info.value.status_code == 409
    assert "full" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_concurrent_bookings_across_different_providers_succeed_simultaneously():
    slots = [
        {
            "availability_id": "slot_alice",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "max_bookings": 1,
            "is_active": True,
            "provider_id": "provider_alice",
        },
        {
            "availability_id": "slot_bob",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "max_bookings": 1,
            "is_active": True,
            "provider_id": "provider_bob",
        },
    ]
    existing_bookings = [
        {
            "booking_id": "b_alice_1",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "date": MONDAY_DATE,
            "start_time": "10:00",
            "end_time": "11:00",
            "status": "confirmed",
            "provider_id": "provider_alice",
        }
    ]
    svc, pb = make_service(slots, existing_bookings)

    bob_booking = {
        "property_id": PROP_ID,
        "date": MONDAY_DATE,
        "start_time": "10:00",
        "end_time": "11:00",
        "provider_id": "provider_bob",
    }
    await svc._booking_slot(pb, "token", SITE_ID, bob_booking)


@pytest.mark.asyncio
async def test_unassigned_provider_auto_assignment_and_capacity():
    slots = [
        {
            "availability_id": "slot_alice",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "max_bookings": 1,
            "is_active": True,
            "provider_id": "provider_alice",
        },
        {
            "availability_id": "slot_bob",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "max_bookings": 1,
            "is_active": True,
            "provider_id": "provider_bob",
        },
    ]
    existing_bookings = [
        {
            "booking_id": "b_alice_1",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "date": MONDAY_DATE,
            "start_time": "10:00",
            "end_time": "11:00",
            "status": "confirmed",
            "provider_id": "provider_alice",
        }
    ]
    svc, pb = make_service(slots, existing_bookings)

    auto_booking = {
        "property_id": PROP_ID,
        "date": MONDAY_DATE,
        "start_time": "10:00",
        "end_time": "11:00",
        "provider_id": "auto",
    }
    await svc._booking_slot(pb, "token", SITE_ID, auto_booking)
    assert auto_booking["provider_id"] == "provider_bob"

    existing_bookings.append(
        {
            "booking_id": "b_bob_1",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "date": MONDAY_DATE,
            "start_time": "10:00",
            "end_time": "11:00",
            "status": "confirmed",
            "provider_id": "provider_bob",
        }
    )
    svc_full, pb_full = make_service(slots, existing_bookings)

    another_booking = {
        "property_id": PROP_ID,
        "date": MONDAY_DATE,
        "start_time": "10:00",
        "end_time": "11:00",
        "provider_id": "auto",
    }
    with pytest.raises(HTTPException) as exc_info:
        await svc_full._booking_slot(pb_full, "token", SITE_ID, another_booking)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_omitted_provider_backward_compatibility_with_generic_slots():
    slots = [
        {
            "availability_id": "slot_generic",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "max_bookings": 2,
            "is_active": True,
        }
    ]
    existing_bookings = [
        {
            "booking_id": "b_1",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "date": MONDAY_DATE,
            "start_time": "10:00",
            "end_time": "11:00",
            "status": "confirmed",
        }
    ]
    svc, pb = make_service(slots, existing_bookings)

    booking_1 = {
        "property_id": PROP_ID,
        "date": MONDAY_DATE,
        "start_time": "10:00",
        "end_time": "11:00",
    }
    await svc._booking_slot(pb, "token", SITE_ID, booking_1)

    existing_bookings.append(
        {
            "booking_id": "b_2",
            "site_id": SITE_ID,
            "property_id": PROP_ID,
            "date": MONDAY_DATE,
            "start_time": "10:00",
            "end_time": "11:00",
            "status": "confirmed",
        }
    )
    svc_full, pb_full = make_service(slots, existing_bookings)

    booking_overflow = {
        "property_id": PROP_ID,
        "date": MONDAY_DATE,
        "start_time": "10:00",
        "end_time": "11:00",
    }
    with pytest.raises(HTTPException) as exc_info:
        await svc_full._booking_slot(pb_full, "token", SITE_ID, booking_overflow)
    assert exc_info.value.status_code == 409
