from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.services.transactional_service import TransactionalService


async def test_pending_order_cancellation_also_cancels_committed_fake_payment():
    """Payment persisted but the preceding pending->paid update was interrupted."""
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "id": "o",
        "order_id": "order",
        "site_id": "site",
        "status": "pending",
    }
    pb.list_records.return_value = {
        "items": [{"id": "p", "method": "fake", "status": "completed"}]
    }
    service = TransactionalService()
    service.get_order = AsyncMock(return_value={})
    await service.update_order(pb, "token", "order", {"status": "cancelled"})
    assert pb.update_record.call_args_list[0].args[:3] == (
        "payments",
        "p",
        {"status": "cancelled"},
    )


async def test_fulfillment_rejects_interrupted_payment_cancellation():
    """Payment cancellation persisted but the order still says paid."""
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "id": "o",
        "order_id": "order",
        "site_id": "site",
        "status": "paid",
        "total": 10,
        "currency": "USD",
    }
    pb.list_records.return_value = {
        "items": [
            {
                "id": "p",
                "method": "fake",
                "status": "cancelled",
                "amount": 10,
                "currency": "USD",
            }
        ]
    }
    service = TransactionalService()
    service.get_order = AsyncMock(return_value={})
    with pytest.raises(HTTPException) as error:
        await service.update_order(pb, "token", "order", {"status": "fulfilled"})
    assert error.value.status_code == 409
    pb.update_record.assert_not_called()


async def test_repeated_cancellation_repairs_remaining_payment():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "id": "o",
        "order_id": "order",
        "site_id": "site",
        "status": "cancelled",
    }
    pb.list_records.return_value = {
        "items": [{"id": "p", "method": "fake", "status": "completed"}]
    }
    service = TransactionalService()
    service.get_order = AsyncMock(return_value={})
    await service.update_order(pb, "token", "order", {"status": "cancelled"})
    assert pb.update_record.call_args_list[0].args[0] == "payments"


async def test_pending_detail_uses_persisted_items_when_cached_total_is_stale():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "id": "o",
        "order_id": "order",
        "site_id": "site",
        "status": "pending",
        "total": 10,
    }
    pb.list_records.side_effect = [
        {
            "items": [
                {
                    "item_id": "i",
                    "order_id": "order",
                    "property_id": "prop",
                    "quantity": 2,
                    "unit_price": 10,
                    "total_price": 20,
                }
            ]
        },
        {"items": []},
        {"items": []},
    ]
    result = await TransactionalService().get_order(pb, "token", "order")
    assert result["total"] == 20
    pb.update_record.assert_not_called()
