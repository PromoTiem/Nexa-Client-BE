"""Scheduling policy for manual bookings and optional weekly availability."""

import re
from datetime import date
from functools import wraps
from inspect import signature

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.infrastructure.operation_lock import operation_lock
from app.infrastructure.pocketbase.filters import sanitize_filter_value

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def validate_status(current, target):
    if target not in TRANSITIONS:
        raise HTTPException(422, "Invalid booking status")
    if current not in TRANSITIONS or (
        target != current and target not in TRANSITIONS[current]
    ):
        raise HTTPException(409, "Invalid booking status transition")


def minutes(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value
    ):
        raise HTTPException(422, "Time must use HH:MM, 00:00 through 23:59")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def interval(record):
    start, end = minutes(record.get("start_time")), minutes(record.get("end_time"))
    if end <= start:
        raise HTTPException(422, "End time must be after start time on the same day")
    return start, end


def booking_date(value):
    try:
        # PocketBase serializes date fields with midnight and timezone suffix.
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}(?:[ T]00:00:00(?:\.000)?Z?)?", value
        ):
            raise ValueError
        return date.fromisoformat(value[:10])
    except ValueError:
        raise HTTPException(
            422, "Date must be a valid YYYY-MM-DD calendar date"
        ) from None


def validate_availability(record):
    interval(record)
    if record.get("day_of_week") not in DAYS:
        raise HTTPException(422, "day_of_week must be a lowercase weekday name")
    capacity = record.get("max_bookings", 0)
    if (
        isinstance(capacity, bool)
        or not isinstance(capacity, (int, float))
        or capacity < 0
        or int(capacity) != capacity
    ):
        raise HTTPException(422, "max_bookings must be a nonnegative integer")
    if not isinstance(record.get("is_active", True), bool):
        raise HTTPException(422, "is_active must be a boolean")


def serialize_schedule(method):
    """Share the lifecycle site lock for availability and booking mutations."""
    parameters = signature(method)

    @wraps(method)
    async def wrapped(*args, **kwargs):
        values = parameters.bind(*args, **kwargs).arguments
        pb, token = values["pb"], values["token"]
        site_id = values.get("site_id")
        if not site_id:
            field = "booking_id" if "booking_id" in values else "availability_id"
            collection = "bookings" if field == "booking_id" else "availability"
            record = await pb.find_one_by_filter(
                collection,
                f'{field}="{sanitize_filter_value(values[field])}"',
                token=token,
            )
            site_id = record["site_id"]
        async with operation_lock("site:" + site_id):
            site = await pb.find_one_by_filter(
                "sites", f'site_id="{sanitize_filter_value(site_id)}"', token=token
            )
            assert_site_active(site)
            return await method(*args, **kwargs)

    return wrapped
