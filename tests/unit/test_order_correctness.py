from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.application.services.order_policy import validate_transition
from app.application.services.transactional_service import TransactionalService
from app.interface.dto.transactional import OrderItemCreate, PaymentCreateRequest


@pytest.mark.parametrize(
    "current,target",
    [
        ("pending", "paid"),
        ("pending", "cancelled"),
        ("paid", "fulfilled"),
        ("paid", "cancelled"),
        ("fulfilled", "fulfilled"),
    ],
)
def test_allowed_transitions(current, target):
    validate_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        ("pending", "fulfilled"),
        ("paid", "pending"),
        ("fulfilled", "paid"),
        ("cancelled", "pending"),
        ("unknown", "paid"),
    ],
)
def test_rejects_backward_and_terminal_transitions(current, target):
    with pytest.raises(HTTPException) as error:
        validate_transition(current, target)
    assert error.value.status_code == 409


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_request_dtos_reject_nonfinite_values(value):
    with pytest.raises(ValidationError):
        OrderItemCreate(property_id="p", quantity=1, unit_price=value)
    with pytest.raises(ValidationError):
        OrderItemCreate(property_id="p", quantity=value, unit_price=1)
    with pytest.raises(ValidationError):
        PaymentCreateRequest(method="manual", amount=value)


@pytest.mark.asyncio
async def test_invalid_transition_makes_no_write():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "id": "r",
        "site_id": "s",
        "status": "cancelled",
    }
    with pytest.raises(HTTPException) as error:
        await TransactionalService().update_order(
            pb, "token", "order_a", {"status": "paid"}
        )
    assert error.value.status_code == 409
    pb.update_record.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_null_status_is_rejected():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "id": "r",
        "site_id": "s",
        "status": "pending",
    }
    with pytest.raises(HTTPException) as error:
        await TransactionalService().update_order(pb, "token", "o", {"status": None})
    assert error.value.status_code == 422
    pb.update_record.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["paid", "fulfilled", "cancelled"])
async def test_settled_orders_reject_item_addition(status):
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"site_id": "s", "status": status}
    with pytest.raises(HTTPException):
        await TransactionalService().add_order_item(
            pb,
            "token",
            "o",
            {
                "property_id": "p",
                "quantity": 1,
                "unit_price": 10,
            },
        )
    pb.create_record.assert_not_called()


@pytest.mark.asyncio
async def test_settled_orders_reject_item_removal():
    pb = AsyncMock()
    pb.find_one_by_filter.side_effect = [
        {"id": "i", "order_id": "o"},
        {"site_id": "s", "status": "paid"},
        {"config": {}},
        {"status": "paid"},
    ]
    with pytest.raises(HTTPException):
        await TransactionalService().delete_order_item(pb, "token", "item")
    pb.delete_record.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["paid", "fulfilled"])
async def test_preserves_financial_order_history(status):
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"site_id": "s", "status": status}
    with pytest.raises(HTTPException):
        await TransactionalService().delete_order(pb, "token", "o")
    pb.update_record.assert_not_called()


@pytest.mark.asyncio
async def test_payment_currency_mismatch_has_no_side_effect():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {
        "site_id": "s",
        "status": "pending",
        "currency": "USD",
    }
    with pytest.raises(HTTPException) as error:
        await TransactionalService().add_payment(
            pb, "token", "o", {"amount": 1, "currency": "VND"}
        )
    assert error.value.status_code == 422
    pb.create_record.assert_not_called()


@pytest.mark.asyncio
async def test_complete_payment_pagination_keeps_scope_and_token():
    pb = AsyncMock()
    first = [{"payment_id": f"p{i}"} for i in range(100)]
    pb.list_records.side_effect = [
        {"items": first, "totalPages": 2},
        {"items": [{"payment_id": "p100"}], "totalPages": 2},
    ]
    result = await TransactionalService().list_payments(pb, "caller", "o")
    assert len(result) == 101
    assert [call.kwargs["page"] for call in pb.list_records.call_args_list] == [1, 2]
    for call in pb.list_records.call_args_list:
        assert call.kwargs["token"] == "caller"
        assert call.kwargs["filter"] == 'order_id="o"'
        assert call.kwargs["sort"] == "id"


@pytest.mark.asyncio
async def test_pagination_gap_does_not_return_partial_success():
    pb = AsyncMock()
    pb.list_records.return_value = {"items": [], "totalPages": 2}
    with pytest.raises(HTTPException) as error:
        await TransactionalService().list_payments(pb, "caller", "o")
    assert error.value.status_code == 502


@pytest.mark.asyncio
async def test_create_rejects_invalid_numbers_without_mutating_request():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"config": {}}
    data = {"items": [{"property_id": "p", "quantity": 1, "unit_price": -1}]}
    before = deepcopy(data)
    with pytest.raises(HTTPException):
        await TransactionalService().create_order(pb, "token", "s", data)
    assert data == before
    pb.create_record.assert_not_called()
