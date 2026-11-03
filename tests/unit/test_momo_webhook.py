from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.config import MomoSettings, Settings, get_settings
from app.infrastructure.momo import generate_signature
from app.infrastructure.momo.dto import MomoIpnPayload
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import get_static_pocketbase_client
from app.interface.exception_handlers import register_exception_handlers
from app.interface.routes.webhooks_momo import momo_webhook_router

SAMPLE_ACCESS_KEY = "SvDmj2cOTYZmQQ3H"
SAMPLE_SECRET_KEY = "PPuDXq1KowPT1ftR8DvlQTHhC03aul17"
SAMPLE_PARTNER_CODE = "MOMOIQA420180417"


def make_signed_ipn_payload(
    order_id: str = "order_test_123",
    amount: int = 50000,
    result_code: int = 0,
    trans_id: int | str = 987654321,
    secret_key: str = SAMPLE_SECRET_KEY,
    access_key: str = SAMPLE_ACCESS_KEY,
    partner_code: str = SAMPLE_PARTNER_CODE,
    tamper_signature: bool = False,
    pay_type: str = "qr",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "accessKey": access_key,
        "amount": amount,
        "extraData": "",
        "message": "Successful." if result_code == 0 else "Transaction failed.",
        "orderId": order_id,
        "orderInfo": "Thanh toan don hang test",
        "orderType": "momo_wallet",
        "partnerCode": partner_code,
        "payType": pay_type,
        "requestId": f"req_{order_id}",
        "responseTime": 1700000000000,
        "resultCode": result_code,
        "transId": trans_id,
    }
    sig = generate_signature(payload, secret_key)
    if tamper_signature:
        payload["signature"] = "tampered_signature_1234567890abcdef"
    else:
        payload["signature"] = sig
    return payload


def create_test_app(mock_pb: AsyncMock) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(momo_webhook_router)

    app.dependency_overrides[get_static_pocketbase_client] = lambda: mock_pb
    test_settings = Settings(
        momo=MomoSettings(
            enabled=True,
            partner_code=SAMPLE_PARTNER_CODE,
            access_key=SAMPLE_ACCESS_KEY,
            secret_key=SAMPLE_SECRET_KEY,
        ),
        rate_limit_storage_uri="memory://",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    return app


@pytest.fixture
def mock_pb() -> AsyncMock:
    pb = AsyncMock(spec=PocketBaseClient)
    return pb


@pytest.mark.asyncio
async def test_valid_ipn_callback_success(mock_pb: AsyncMock) -> None:
    """Test valid IPN callback with resultCode=0 transitioning order to paid and payment to completed."""
    order_record = {
        "id": "rec_order_123",
        "order_id": "order_test_123",
        "status": "pending",
        "total": 50000,
    }
    payment_record = {
        "id": "rec_pay_456",
        "payment_id": "pay_test_456",
        "order_id": "order_test_123",
        "status": "pending",
    }

    mock_pb.find_one_by_filter.return_value = order_record
    mock_pb.list_records.return_value = {"items": [payment_record]}

    payload = make_signed_ipn_payload(
        order_id="order_test_123",
        amount=50000,
        result_code=0,
        trans_id=987654321,
        pay_type="qr",
    )

    app = create_test_app(mock_pb)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/webhooks/momo/ipn", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "resultCode": 0,
        "message": "Received IPN successfully",
    }

    # Verify payments record updated to completed with trans_id, pay_type, raw_payload
    mock_pb.update_record.assert_any_await(
        "payments",
        "rec_pay_456",
        {
            "status": "completed",
            "trans_id": "987654321",
            "pay_type": "qr",
            "raw_payload": payload,
        },
    )

    # Verify orders record updated to paid
    mock_pb.update_record.assert_any_await(
        "orders",
        "rec_order_123",
        {"status": "paid"},
    )


@pytest.mark.asyncio
async def test_tampered_signature_returns_400(mock_pb: AsyncMock) -> None:
    """Test tampered signature triggering HTTP 400 Bad Request."""
    payload = make_signed_ipn_payload(
        order_id="order_test_123",
        amount=50000,
        result_code=0,
        tamper_signature=True,
    )

    app = create_test_app(mock_pb)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/webhooks/momo/ipn", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid HMAC signature"}
    mock_pb.find_one_by_filter.assert_not_called()
    mock_pb.update_record.assert_not_called()


@pytest.mark.asyncio
async def test_amount_mismatch_returns_400(mock_pb: AsyncMock) -> None:
    """Test amount mismatch triggering HTTP 400."""
    order_record = {
        "id": "rec_order_123",
        "order_id": "order_test_123",
        "status": "pending",
        "total": 50000,
    }
    mock_pb.find_one_by_filter.return_value = order_record

    # Payload amount is 100000, but order is 50000 (validly signed for 100000)
    payload = make_signed_ipn_payload(
        order_id="order_test_123",
        amount=100000,
        result_code=0,
    )

    app = create_test_app(mock_pb)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/webhooks/momo/ipn", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "Amount mismatch"}
    mock_pb.update_record.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_ipn_replay_order_already_paid(mock_pb: AsyncMock) -> None:
    """Test duplicate IPN replay returning HTTP 200 idempotently when order is already paid."""
    order_record = {
        "id": "rec_order_123",
        "order_id": "order_test_123",
        "status": "paid",
        "total": 50000,
    }
    payment_record = {
        "id": "rec_pay_456",
        "payment_id": "pay_test_456",
        "order_id": "order_test_123",
        "status": "completed",
    }

    mock_pb.find_one_by_filter.return_value = order_record
    mock_pb.list_records.return_value = {"items": [payment_record]}

    payload = make_signed_ipn_payload(
        order_id="order_test_123",
        amount=50000,
        result_code=0,
    )

    app = create_test_app(mock_pb)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/webhooks/momo/ipn", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "resultCode": 0,
        "message": "Received IPN successfully",
    }
    # No updates to PB
    mock_pb.update_record.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_ipn_replay_payment_already_completed(
    mock_pb: AsyncMock,
) -> None:
    """Test duplicate IPN replay returning HTTP 200 idempotently when payment is already completed."""
    order_record = {
        "id": "rec_order_123",
        "order_id": "order_test_123",
        "status": "pending",
        "total": 50000,
    }
    payment_record = {
        "id": "rec_pay_456",
        "payment_id": "pay_test_456",
        "order_id": "order_test_123",
        "status": "completed",
    }

    mock_pb.find_one_by_filter.return_value = order_record
    mock_pb.list_records.return_value = {"items": [payment_record]}

    payload = make_signed_ipn_payload(
        order_id="order_test_123",
        amount=50000,
        result_code=0,
    )

    app = create_test_app(mock_pb)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/webhooks/momo/ipn", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "resultCode": 0,
        "message": "Received IPN successfully",
    }
    # No updates to PB
    mock_pb.update_record.assert_not_called()


@pytest.mark.asyncio
async def test_result_code_nonzero_marks_payment_failed_order_pending(
    mock_pb: AsyncMock,
) -> None:
    """Test resultCode != 0 marking payment as failed while order remains pending."""
    order_record = {
        "id": "rec_order_123",
        "order_id": "order_test_123",
        "status": "pending",
        "total": 50000,
    }
    payment_record = {
        "id": "rec_pay_456",
        "payment_id": "pay_test_456",
        "order_id": "order_test_123",
        "status": "pending",
    }

    mock_pb.find_one_by_filter.return_value = order_record
    mock_pb.list_records.return_value = {"items": [payment_record]}

    # resultCode=1006 (cancelled by user)
    payload = make_signed_ipn_payload(
        order_id="order_test_123",
        amount=50000,
        result_code=1006,
        trans_id=11223344,
    )

    app = create_test_app(mock_pb)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/webhooks/momo/ipn", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "resultCode": 0,
        "message": "Received IPN successfully",
    }

    # Verify payment record updated to failed
    mock_pb.update_record.assert_called_once_with(
        "payments",
        "rec_pay_456",
        {
            "status": "failed",
            "raw_payload": payload,
        },
    )

    # Verify orders record was NEVER updated (remains pending)
    assert not any(
        call.args[0] == "orders" for call in mock_pb.update_record.call_args_list
    )


@pytest.mark.asyncio
async def test_order_not_found_returns_404(mock_pb: AsyncMock) -> None:
    """Test non-existent order returning HTTP 404."""
    mock_pb.find_one_by_filter.side_effect = HTTPException(
        status_code=404, detail="Record not found"
    )

    payload = make_signed_ipn_payload(
        order_id="order_nonexistent",
        amount=50000,
        result_code=0,
    )

    app = create_test_app(mock_pb)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/webhooks/momo/ipn", json=payload)

    assert response.status_code == 404
    assert response.json() == {"detail": "Order not found"}
    mock_pb.update_record.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_creates_payment_record_if_none_exists(
    mock_pb: AsyncMock,
) -> None:
    """Test creating payment record if matching payment record did not exist initially."""
    order_record = {
        "id": "rec_order_123",
        "order_id": "order_test_123",
        "status": "pending",
        "total": 50000,
    }
    mock_pb.find_one_by_filter.return_value = order_record
    mock_pb.list_records.return_value = {"items": []}

    payload = make_signed_ipn_payload(
        order_id="order_test_123",
        amount=50000,
        result_code=0,
        trans_id=987654321,
    )

    app = create_test_app(mock_pb)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/webhooks/momo/ipn", json=payload)

    assert response.status_code == 200
    mock_pb.create_record.assert_awaited_once()
    assert mock_pb.create_record.call_args[0][0] == "payments"
    created_payment = mock_pb.create_record.call_args[0][1]
    assert created_payment["status"] == "completed"
    assert created_payment["trans_id"] == "987654321"
    assert created_payment["order_id"] == "order_test_123"

    mock_pb.update_record.assert_called_once_with(
        "orders", "rec_order_123", {"status": "paid"}
    )


@pytest.mark.asyncio
async def test_handle_momo_ipn_with_momo_ipn_payload_instance(
    mock_pb: AsyncMock,
) -> None:
    """Test calling handle_momo_ipn directly with a MomoIpnPayload instance."""
    order_record = {
        "id": "rec_order_123",
        "order_id": "order_test_123",
        "status": "pending",
        "total": 50000,
    }
    payment_record = {
        "id": "rec_pay_456",
        "payment_id": "pay_test_456",
        "order_id": "order_test_123",
        "status": "pending",
    }
    mock_pb.find_one_by_filter.return_value = order_record
    mock_pb.list_records.return_value = {"items": [payment_record]}

    payload_dict = make_signed_ipn_payload(
        order_id="order_test_123",
        amount=50000,
        result_code=0,
        trans_id=987654321,
    )
    ipn_model = MomoIpnPayload.model_validate(payload_dict)
    test_settings = Settings(
        momo=MomoSettings(
            enabled=True,
            partner_code=SAMPLE_PARTNER_CODE,
            access_key=SAMPLE_ACCESS_KEY,
            secret_key=SAMPLE_SECRET_KEY,
        ),
        rate_limit_storage_uri="memory://",
    )
    from app.interface.routes.webhooks_momo import handle_momo_ipn

    result = await handle_momo_ipn(
        payload=ipn_model,
        pb=mock_pb,
        settings=test_settings,
    )
    assert result == {
        "resultCode": 0,
        "message": "Received IPN successfully",
    }


@pytest.mark.asyncio
async def test_main_app_has_momo_webhook_router_registered(
    client: httpx.AsyncClient, mock_pb: AsyncMock
) -> None:
    from app.main import app

    app.dependency_overrides[get_static_pocketbase_client] = lambda: mock_pb
    response = await client.post("/public/webhooks/momo/ipn", json={})
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid HMAC signature"}
