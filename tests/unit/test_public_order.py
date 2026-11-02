from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.infrastructure.momo.client import MomoGatewayClient, MomoGatewayError
from app.infrastructure.momo.dto import MomoCreatePaymentResponse
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.rate_limits import get_limiter
from app.interface.dependencies import get_static_pocketbase_client
from app.interface.exception_handlers import register_exception_handlers
from app.interface.routes.public_order import get_momo_client, public_order_router

SITE_ID = "site_alpha_123"


def create_test_app(mock_pb: AsyncMock, mock_momo: AsyncMock | None = None) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(public_order_router)

    app.dependency_overrides[get_static_pocketbase_client] = lambda: mock_pb
    if mock_momo is not None:
        app.dependency_overrides[get_momo_client] = lambda: mock_momo
    app.dependency_overrides[get_settings] = lambda: Settings(
        rate_limit_storage_uri="memory://"
    )
    get_limiter("memory://").storage.reset()
    return app


@pytest.fixture
def mock_pb() -> AsyncMock:
    pb = AsyncMock(spec=PocketBaseClient)
    pb.create_record.return_value = {"id": "rec_test_123"}
    return pb


@pytest.mark.asyncio
async def test_create_order_cod_success(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Nguyen Van A",
        "customer_phone": "0901234567",
        "customer_email": "nguyenvana@example.com",
        "shipping_address": "123 Le Loi, District 1, Ho Chi Minh City",
        "payment_method": "cod",
        "items": [
            {
                "property_id": "prop_item_1",
                "quantity": 2,
                "unit_price": 50000,
            }
        ],
        "notes": "Please call before delivery",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["order_id"].startswith("order_")
    assert data["status"] == "pending"
    assert data["total"] == 100000
    assert data["currency"] == "VND"
    assert data["payment_method"] == "cod"
    assert data["payment_id"].startswith("pay_")
    assert data["pay_url"] is None
    assert data["deeplink"] is None
    assert data["customer_name"] == "Nguyen Van A"
    assert data["customer_phone"] == "0901234567"
    assert data["customer_email"] == "nguyenvana@example.com"

    # Verify orders collection insert
    order_calls = [
        call
        for call in mock_pb.create_record.call_args_list
        if call.args[0] == "orders"
    ]
    assert len(order_calls) == 1
    order_data = order_calls[0].args[1]
    assert order_data["site_id"] == SITE_ID
    assert order_data["status"] == "pending"
    assert order_data["total"] == 100000
    assert order_data["currency"] == "VND"
    assert order_data["metadata"]["payment_method"] == "cod"
    assert (
        order_data["metadata"]["shipping_address"]
        == "123 Le Loi, District 1, Ho Chi Minh City"
    )

    # Verify order_items collection insert
    item_calls = [
        call
        for call in mock_pb.create_record.call_args_list
        if call.args[0] == "order_items"
    ]
    assert len(item_calls) == 1
    item_data = item_calls[0].args[1]
    assert item_data["property_id"] == "prop_item_1"
    assert item_data["quantity"] == 2
    assert item_data["unit_price"] == 50000
    assert item_data["total_price"] == 100000

    # Verify payments collection insert
    payment_calls = [
        call
        for call in mock_pb.create_record.call_args_list
        if call.args[0] == "payments"
    ]
    assert len(payment_calls) == 1
    payment_data = payment_calls[0].args[1]
    assert payment_data["method"] == "cod"
    assert payment_data["status"] == "pending"
    assert payment_data["amount"] == 100000
    assert payment_data["currency"] == "VND"


@pytest.mark.asyncio
async def test_create_order_momo_success(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Tran Thi B",
        "customer_phone": "0987654321",
        "customer_email": "tranthib@example.com",
        "shipping_address": "456 Nguyen Hue, Da Nang",
        "payment_method": "momo",
        "items": [
            {
                "property_id": "prop_item_2",
                "quantity": 1,
                "unit_price": 250000,
            }
        ],
    }

    momo_mock_response = MomoCreatePaymentResponse(
        partnerCode="MOMOBKUN20180529",
        orderId="order_mock",
        requestId="req_mock",
        amount=250000,
        responseTime=1700000000,
        message="Success",
        resultCode=0,
        payUrl="https://test-payment.momo.vn/v2/gateway/pay?s=sample_pay_token",
        deeplink="momo://app?action=pay&token=sample_pay_token",
        qrCodeUrl="https://test-payment.momo.vn/v2/gateway/pay/qr?s=sample_pay_token",
    )

    with patch.object(
        MomoGatewayClient, "create_payment", new_callable=AsyncMock
    ) as mock_create_payment:
        mock_create_payment.return_value = momo_mock_response

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/public/sites/{SITE_ID}/orders", json=payload
            )

        mock_create_payment.assert_awaited_once()

    assert response.status_code == 201
    data = response.json()
    assert data["order_id"].startswith("order_")
    assert data["status"] == "pending"
    assert data["total"] == 250000
    assert data["currency"] == "VND"
    assert data["payment_method"] == "momo"
    assert (
        data["pay_url"]
        == "https://test-payment.momo.vn/v2/gateway/pay?s=sample_pay_token"
    )
    assert data["deeplink"] == "momo://app?action=pay&token=sample_pay_token"
    assert (
        data["qr_code_url"]
        == "https://test-payment.momo.vn/v2/gateway/pay/qr?s=sample_pay_token"
    )

    # Verify payments collection insert with gateway=momo
    payment_calls = [
        call
        for call in mock_pb.create_record.call_args_list
        if call.args[0] == "payments"
    ]
    assert len(payment_calls) == 1
    payment_data = payment_calls[0].args[1]
    assert payment_data["gateway"] == "momo"
    assert payment_data["method"] == "momo"
    assert payment_data["status"] == "pending"
    assert payment_data["amount"] == 250000
    assert payment_data["currency"] == "VND"
    assert payment_data["request_id"].startswith("req_")
    assert payment_data["partner_code"] == "MOMOBKUN20180529"


@pytest.mark.asyncio
async def test_create_order_bank_transfer_success(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Le Van C",
        "customer_phone": "0912345678",
        "payment_method": "bank",
        "items": [
            {
                "property_id": "prop_item_3",
                "quantity": 3,
                "unit_price": 100000,
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["payment_method"] == "bank"
    assert data["total"] == 300000
    assert data["pay_url"] is None

    payment_calls = [
        call
        for call in mock_pb.create_record.call_args_list
        if call.args[0] == "payments"
    ]
    assert len(payment_calls) == 1
    assert payment_calls[0].args[1]["method"] == "bank"


@pytest.mark.asyncio
async def test_rejection_on_amount_less_than_1000(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Test User",
        "payment_method": "cod",
        "items": [
            {
                "property_id": "prop_item_cheap",
                "quantity": 1,
                "unit_price": 500,
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Order amount must be at least 1,000 VND"
    mock_pb.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejection_on_explicit_total_less_than_1000(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Test User",
        "payment_method": "cod",
        "total": 999,
        "items": [
            {
                "property_id": "prop_item_valid",
                "quantity": 1,
                "unit_price": 10000,
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 422
    assert "Order amount must be at least 1,000 VND" in response.text
    mock_pb.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejection_on_amount_greater_than_50_million(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Big Spender",
        "payment_method": "cod",
        "total": 50000001,
        "items": [
            {
                "property_id": "prop_item_expensive",
                "quantity": 1,
                "unit_price": 50000001,
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 422
    assert "Order amount must not exceed 50,000,000 VND" in response.text
    mock_pb.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejection_on_empty_line_items(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Test User",
        "payment_method": "cod",
        "items": [],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 422
    mock_pb.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejection_on_zero_quantity(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Test User",
        "payment_method": "cod",
        "items": [
            {
                "property_id": "prop_item_1",
                "quantity": 0,
                "unit_price": 50000,
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 422
    mock_pb.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejection_on_invalid_site_id(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Test User",
        "payment_method": "cod",
        "items": [
            {
                "property_id": "prop_item_1",
                "quantity": 1,
                "unit_price": 50000,
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/public/sites/invalid%20site%20id/orders", json=payload
        )

    assert response.status_code == 400
    mock_pb.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejection_on_unsupported_payment_method(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Test User",
        "payment_method": "crypto",
        "items": [
            {
                "property_id": "prop_item_1",
                "quantity": 1,
                "unit_price": 50000,
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 422
    assert "Unsupported payment method" in response.text
    mock_pb.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejection_on_negative_unit_price(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Test User",
        "payment_method": "cod",
        "items": [
            {
                "property_id": "prop_item_1",
                "quantity": 1,
                "unit_price": -100,
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)

    assert response.status_code == 422
    mock_pb.create_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_momo_gateway_error_returns_502(mock_pb: AsyncMock) -> None:
    app = create_test_app(mock_pb)
    payload = {
        "customer_name": "Test User",
        "payment_method": "momo",
        "items": [
            {
                "property_id": "prop_item_1",
                "quantity": 1,
                "unit_price": 50000,
            }
        ],
    }

    with patch.object(
        MomoGatewayClient,
        "create_payment",
        side_effect=MomoGatewayError("Connection timeout to MoMo upstream"),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/public/sites/{SITE_ID}/orders", json=payload
            )

    assert response.status_code == 502
    assert "MoMo gateway error" in response.text


@pytest.mark.asyncio
async def test_main_app_has_public_order_route_registered(
    client: httpx.AsyncClient, mock_pb: AsyncMock
) -> None:
    from app.main import app

    app.dependency_overrides[get_static_pocketbase_client] = lambda: mock_pb
    payload = {
        "customer_name": "End to End",
        "payment_method": "cod",
        "items": [
            {
                "property_id": "prop_item_1",
                "quantity": 1,
                "unit_price": 10000,
            }
        ],
    }

    response = await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
