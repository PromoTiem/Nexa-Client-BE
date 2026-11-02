from unittest.mock import AsyncMock

import pytest

from app.application.services.transactional_service import TransactionalService
from app.infrastructure.momo.client import MomoGatewayError
from app.infrastructure.momo.dto import MomoQueryResponse


@pytest.fixture
def mock_pb():
    pb = AsyncMock()

    # Mock find_one_by_filter for order and site (needed by @serialize_order)
    def find_one_side_effect(collection, filter_str, token=None):
        if collection == "orders":
            return {
                "id": "order_record_1",
                "order_id": "ORD-123",
                "site_id": "site_test_1",
                "status": "pending",
                "currency": "VND",
                "total": 50000,
            }
        if collection == "sites":
            return {
                "id": "site_record_1",
                "site_id": "site_test_1",
                "status": "active",
            }
        return {}

    pb.find_one_by_filter.side_effect = find_one_side_effect
    return pb


@pytest.mark.asyncio
async def test_reconcile_momo_payment_success(mock_pb):
    """Test order reconciliation when MoMo reports resultCode=0 (updates payment to completed and order to paid)."""
    service = TransactionalService()

    # Payments returned for order
    payments = [
        {
            "id": "pay_rec_1",
            "payment_id": "pay_1",
            "order_id": "ORD-123",
            "gateway": "momo",
            "method": "momo",
            "status": "pending",
            "request_id": "req_123",
        }
    ]
    service._order_children = AsyncMock(return_value=payments)
    service.get_order = AsyncMock(
        return_value={"order_id": "ORD-123", "status": "paid"}
    )

    momo_client = AsyncMock()
    momo_client.query_payment.return_value = MomoQueryResponse(
        partnerCode="MOMOIQA420180417",
        orderId="ORD-123",
        requestId="req_123",
        amount=50000,
        transId=987654321,
        resultCode=0,
        message="Thành công",
    )

    result = await service.reconcile_momo_payment(
        mock_pb,
        token="test_token",
        order_id="ORD-123",
        user_id="user_1",
        momo_client=momo_client,
    )

    # Verify MoMo query was called with correct parameters
    momo_client.query_payment.assert_awaited_once_with(
        order_id="ORD-123",
        request_id="req_123",
    )

    # Verify payment record updated to completed with trans_id
    mock_pb.update_record.assert_any_await(
        "payments",
        "pay_rec_1",
        {"status": "completed", "trans_id": "987654321"},
        token="test_token",
        user_id="user_1",
    )

    # Verify order record updated to paid
    mock_pb.update_record.assert_any_await(
        "orders",
        "order_record_1",
        {"status": "paid"},
        token="test_token",
        user_id="user_1",
    )

    assert result["status"] == "paid"


@pytest.mark.asyncio
async def test_reconcile_momo_payment_noop_when_already_paid(mock_pb):
    """Test no-op when order is already paid or fulfilled."""
    mock_pb.find_one_by_filter.side_effect = lambda coll, filt, token=None: (
        {
            "id": "order_record_1",
            "order_id": "ORD-PAID",
            "site_id": "site_test_1",
            "status": "paid",
        }
        if coll == "orders"
        else {
            "id": "site_record_1",
            "site_id": "site_test_1",
            "status": "active",
        }
    )

    service = TransactionalService()
    service._order_children = AsyncMock()
    service.get_order = AsyncMock(
        return_value={"order_id": "ORD-PAID", "status": "paid"}
    )

    momo_client = AsyncMock()

    result = await service.reconcile_momo_payment(
        mock_pb,
        token="test_token",
        order_id="ORD-PAID",
        momo_client=momo_client,
    )

    # Verify no external gateway query was made
    momo_client.query_payment.assert_not_called()
    # Verify no records updated in PocketBase
    mock_pb.update_record.assert_not_called()
    assert result["status"] == "paid"


@pytest.mark.asyncio
async def test_reconcile_momo_payment_cancelled_result(mock_pb):
    """Test handling when MoMo reports cancelled (resultCode=1006, marks payment failed, leaves order pending)."""
    service = TransactionalService()

    payments = [
        {
            "id": "pay_rec_1",
            "payment_id": "pay_1",
            "order_id": "ORD-123",
            "gateway": "momo",
            "method": "momo",
            "status": "pending",
            "request_id": "req_123",
        }
    ]
    service._order_children = AsyncMock(return_value=payments)
    service.get_order = AsyncMock(
        return_value={"order_id": "ORD-123", "status": "pending"}
    )

    momo_client = AsyncMock()
    momo_client.query_payment.return_value = MomoQueryResponse(
        partnerCode="MOMOIQA420180417",
        orderId="ORD-123",
        requestId="req_123",
        amount=50000,
        resultCode=1006,
        message="Giao dịch bị từ chối bởi người dùng",
    )

    result = await service.reconcile_momo_payment(
        mock_pb,
        token="test_token",
        order_id="ORD-123",
        user_id="user_1",
        momo_client=momo_client,
    )

    # Verify payment record updated to failed
    mock_pb.update_record.assert_called_once_with(
        "payments",
        "pay_rec_1",
        {"status": "failed"},
        token="test_token",
        user_id="user_1",
    )

    # Order should NOT be marked paid
    assert not any(
        call.args[0] == "orders" for call in mock_pb.update_record.call_args_list
    )
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_reconcile_momo_payment_connection_error_graceful_handling(mock_pb):
    """Test graceful error handling when MoMo API returns connection / gateway error."""
    service = TransactionalService()

    payments = [
        {
            "id": "pay_rec_1",
            "payment_id": "pay_1",
            "order_id": "ORD-123",
            "gateway": "momo",
            "method": "momo",
            "status": "pending",
            "request_id": "req_123",
        }
    ]
    service._order_children = AsyncMock(return_value=payments)
    service.get_order = AsyncMock(
        return_value={"order_id": "ORD-123", "status": "pending"}
    )

    momo_client = AsyncMock()
    momo_client.query_payment.side_effect = MomoGatewayError("Connection refused")

    result = await service.reconcile_momo_payment(
        mock_pb,
        token="test_token",
        order_id="ORD-123",
        momo_client=momo_client,
    )

    # Should not raise exception, no update to PocketBase
    mock_pb.update_record.assert_not_called()
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_reconcile_momo_payment_noop_when_no_pending_momo_payment(mock_pb):
    """Test no-op when order has no pending MoMo payment."""
    service = TransactionalService()

    # Case 1: no payments
    service._order_children = AsyncMock(return_value=[])
    service.get_order = AsyncMock(
        return_value={"order_id": "ORD-123", "status": "pending"}
    )

    momo_client = AsyncMock()

    result = await service.reconcile_momo_payment(
        mock_pb,
        token="test_token",
        order_id="ORD-123",
        momo_client=momo_client,
    )

    momo_client.query_payment.assert_not_called()
    mock_pb.update_record.assert_not_called()
    assert result["status"] == "pending"

    # Case 2: payment is already completed or COD
    service._order_children = AsyncMock(
        return_value=[
            {
                "id": "pay_cod",
                "payment_id": "pay_2",
                "order_id": "ORD-123",
                "gateway": "cod",
                "method": "cod",
                "status": "pending",
            }
        ]
    )
    result = await service.reconcile_momo_payment(
        mock_pb,
        token="test_token",
        order_id="ORD-123",
        momo_client=momo_client,
    )
    momo_client.query_payment.assert_not_called()
    mock_pb.update_record.assert_not_called()
