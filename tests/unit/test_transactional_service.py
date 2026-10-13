from unittest.mock import AsyncMock

import pytest

from app.application.services.transactional_service import TransactionalService


@pytest.mark.asyncio
async def test_order_detail_resolves_property_items_and_payments():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "order_id": "order_1",
        "site_id": "site_1",
        "status": "paid",
        "total": 20,
        "currency": "USD",
        "customer_name": "Customer",
    }
    pb.list_records.side_effect = [
        {
            "items": [
                {
                    "item_id": "item_1",
                    "order_id": "order_1",
                    "property_id": "prop_1",
                    "quantity": 2,
                    "unit_price": 10,
                    "total_price": 20,
                }
            ]
        },
        {
            "items": [
                {
                    "payment_id": "pay_1",
                    "order_id": "order_1",
                    "method": "cod",
                    "amount": 20,
                    "currency": "USD",
                    "status": "pending",
                }
            ]
        },
        {
            "items": [
                {
                    "property_id": "prop_1",
                    "site_id": "site_1",
                    "name": "Service",
                    "type": "spa_service",
                    "status": "published",
                }
            ]
        },
    ]

    result = await TransactionalService().get_order(pb, "token", "order_1")

    assert result["items"][0]["property"]["name"] == "Service"
    assert result["payments"][0]["payment_id"] == "pay_1"


@pytest.mark.asyncio
async def test_booking_detail_enforces_site_filter_and_resolves_property():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "booking_id": "booking_1",
        "site_id": "site_1",
        "property_id": "prop_1",
        "customer_name": "Customer",
        "customer_email": "customer@example.com",
        "date": "2026-10-02",
        "start_time": "10:00",
        "end_time": "11:00",
        "status": "pending",
    }
    pb.list_records.return_value = {
        "items": [
            {
                "property_id": "prop_1",
                "site_id": "site_1",
                "name": "Massage",
                "type": "spa_service",
            }
        ]
    }

    result = await TransactionalService().get_booking(
        pb, "token", "booking_1", "site_1"
    )

    assert result["property_id"] == "prop_1"
    assert result["property"]["name"] == "Massage"
    assert 'site_id="site_1"' in pb.find_one_by_filter.call_args.args[1]
