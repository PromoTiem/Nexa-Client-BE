from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.application.services.public_site_events import (
    subscribe_newsletter,
    track_public_event,
)
from app.interface.dto.public_events import PublicAnalyticsEvent

SITE = {
    "site_id": "site",
    "tenant_id": "tenant",
    "status": "live",
    "config": {
        "public_submissions": {
            "enabled": True,
            "types": ["booking_submission", "newsletter_subscription"],
        }
    },
}


def _pb(site=SITE, existing=None):
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = site
    pb.list_records.return_value = {
        "items": existing or [],
        "totalItems": len(existing or []),
    }
    pb.create_record.return_value = {"property_id": "sub_x"}
    return pb


async def test_subscription_is_stored_once_per_email():
    pb = _pb()
    await subscribe_newsletter(pb, "site", "Guest@Example.com ")
    data = pb.create_record.call_args.kwargs["data"]
    assert data["type"] == "newsletter_subscription"
    assert data["fields"] == [
        {
            "key": "email",
            "label": "Email",
            "type": "email",
            "required": True,
            "value": "guest@example.com",
        }
    ]
    assert data["property_id"].startswith("sub_")
    assert "guest@example.com" not in data["property_id"]


async def test_repeat_subscription_is_accepted_without_a_second_record():
    pb = _pb(existing=[{"property_id": "sub_x"}])
    await subscribe_newsletter(pb, "site", "guest@example.com")
    pb.create_record.assert_not_awaited()


async def test_subscription_requires_site_opt_in():
    site = {
        **SITE,
        "config": {
            "public_submissions": {"enabled": True, "types": ["booking_submission"]}
        },
    }
    pb = _pb(site=site)
    with pytest.raises(HTTPException) as exc:
        await subscribe_newsletter(pb, "site", "guest@example.com")
    assert exc.value.status_code == 404
    pb.create_record.assert_not_awaited()


async def test_invalid_email_is_rejected():
    pb = _pb()
    with pytest.raises(HTTPException) as exc:
        await subscribe_newsletter(pb, "site", "not-an-email")
    assert exc.value.status_code == 400
    pb.create_record.assert_not_awaited()


async def test_public_event_is_recorded_with_the_sites_tenant():
    pb, collector = _pb(), AsyncMock()
    collector.record_event.return_value = "evt_1"
    event = PublicAnalyticsEvent(
        site_id="site", event_type="page_view", session_id="s1"
    )
    assert await track_public_event(pb, collector, event) == "evt_1"
    kwargs = collector.record_event.call_args.kwargs
    assert kwargs["tenant_id"] == "tenant"
    assert kwargs["event_type"] == "page_view"


async def test_public_event_for_a_property_of_another_site_is_rejected():
    pb, collector = _pb(), AsyncMock()
    pb.find_one_by_filter.side_effect = [SITE, HTTPException(404, "Not found")]
    event = PublicAnalyticsEvent(
        site_id="site", event_type="product_view", property_id="other"
    )
    with pytest.raises(HTTPException) as exc:
        await track_public_event(pb, collector, event)
    assert exc.value.status_code == 404
    collector.record_event.assert_not_awaited()


async def test_inactive_site_does_not_record():
    pb, collector = (
        _pb(site={**SITE, "config": {"_nexa_lifecycle": {"deleted_at": "2026-01-01"}}}),
        AsyncMock(),
    )
    with pytest.raises(HTTPException):
        await track_public_event(
            pb, collector, PublicAnalyticsEvent(site_id="site", event_type="page_view")
        )
    collector.record_event.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"site_id": "site", "event_type": "purchase"},
        {"site_id": "site", "event_type": "page_view", "tenant_id": "spoofed"},
        {"site_id": "site", "event_type": "page_view", "metadata": {"x": "y" * 20000}},
        {"site_id": "../x", "event_type": "page_view"},
    ],
)
def test_public_event_payload_is_constrained(payload):
    with pytest.raises(ValidationError):
        PublicAnalyticsEvent(**payload)
