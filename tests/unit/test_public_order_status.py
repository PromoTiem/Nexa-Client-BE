"""GET /public/sites/{site_id}/orders/{order_id}: the storefront's MoMo poll.

The storefront polls every 3 s and reads ``status``: "paid"/"completed" ends in
success, "cancelled"/"failed" stops polling. The body must never carry PII.
"""

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.config import EcommerceSettings, MomoSettings, Settings, get_settings
from app.infrastructure.momo.client import MomoGatewayClient
from app.infrastructure.momo.dto import MomoCreatePaymentResponse
from app.infrastructure.rate_limits import get_limiter
from app.interface.dependencies import get_static_pocketbase_client
from app.interface.exception_handlers import register_exception_handlers
from app.interface.routes.public_order import get_momo_client, public_order_router
from app.interface.routes.webhooks_momo import momo_webhook_router
from tests.fake_pocketbase import FakePocketBase
from tests.unit.test_momo_webhook import (
    SAMPLE_ACCESS_KEY,
    SAMPLE_PARTNER_CODE,
    SAMPLE_SECRET_KEY,
    make_signed_ipn_payload,
)

SITE_ID = "site_alpha_123"
OTHER_SITE = "site_beta_456"
PII = ("Nguyen Van A", "0901234567", "guest@example.com", "123 Le Loi")
EXPECTED_KEYS = {"order_id", "status", "payment_status", "total", "currency"}


def order(order_id: str, status: str, *, site_id: str = SITE_ID, **extra: Any):
    return {
        "id": f"rec_{order_id}",
        "order_id": order_id,
        "site_id": site_id,
        "customer_name": PII[0],
        "customer_phone": PII[1],
        "customer_email": PII[2],
        "status": status,
        "total": 720_000,
        "currency": "VND",
        "notes": "ring the bell",
        "metadata": {"shipping_address": PII[3], "payment_method": "momo"},
        "deleted_at": "",
        "created_at": "2026-11-16T01:00:00Z",
        **extra,
    }


def payment(order_id: str, status: str, created_at: str) -> dict[str, Any]:
    return {
        "id": f"rec_pay_{order_id}_{created_at[-3:]}",
        "payment_id": f"pay_{order_id}_{created_at[-3:]}",
        "order_id": order_id,
        "gateway": "momo",
        "method": "momo",
        "status": status,
        "amount": 720_000,
        "created_at": created_at,
    }


def build_app(pb: FakePocketBase, momo_client: Any = None) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(public_order_router)
    app.include_router(momo_webhook_router)
    app.dependency_overrides[get_static_pocketbase_client] = lambda: pb
    if momo_client is not None:
        app.dependency_overrides[get_momo_client] = lambda: momo_client
    settings = Settings(
        rate_limit_storage_uri="memory://",
        momo=MomoSettings(
            enabled=True,
            partner_code=SAMPLE_PARTNER_CODE,
            access_key=SAMPLE_ACCESS_KEY,
            secret_key=SAMPLE_SECRET_KEY,
            ipn_url="https://client-be.test/public/webhooks/momo/ipn",
            redirect_url="https://shop.test/checkout/success",
        ),
        ecommerce=EcommerceSettings(
            prices={"p-ly-gom": 720_000}, free_shipping_threshold=0, shipping_fee=0
        ),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    get_limiter("memory://").storage.reset()
    return app


async def get_status(
    app: FastAPI, order_id: str, site_id: str = SITE_ID
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(f"/public/sites/{site_id}/orders/{order_id}")


def assert_no_pii(response: httpx.Response) -> None:
    assert set(response.json()) == EXPECTED_KEYS
    for value in PII:
        assert value not in response.text


@pytest.mark.parametrize(
    "order_status,payments,expected_status,expected_payment",
    [
        ("paid", [("completed", "001")], "paid", "completed"),
        ("fulfilled", [("completed", "001")], "paid", "completed"),
        ("pending", [("pending", "001")], "pending", "pending"),
        ("pending", [], "pending", None),
        ("cancelled", [("failed", "001")], "cancelled", "failed"),
        # A declined MoMo IPN fails the payment but leaves the order pending.
        ("pending", [("pending", "001"), ("failed", "002")], "failed", "failed"),
        # IPN marks the payment completed before the order; both count as paid,
        # the same rule the IPN handler uses for idempotency.
        ("pending", [("completed", "002"), ("pending", "001")], "paid", "completed"),
    ],
)
async def test_status_maps_order_and_latest_payment(
    order_status: str,
    payments: list[tuple[str, str]],
    expected_status: str,
    expected_payment: str | None,
) -> None:
    pb = FakePocketBase(
        orders=[order("order_abc", order_status)],
        payments=[
            payment("order_abc", status, f"2026-11-16T01:00:00.{stamp}Z")
            for status, stamp in payments
        ],
    )

    response = await get_status(build_app(pb), "order_abc")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "order_id": "order_abc",
        "status": expected_status,
        "payment_status": expected_payment,
        "total": 720_000,
        "currency": "VND",
    }
    assert_no_pii(response)


@pytest.mark.parametrize(
    "order_id,site_id",
    [
        ("order_other_site", SITE_ID),
        ("order_abc", OTHER_SITE),
        ("order_missing", SITE_ID),
        ("order_deleted", SITE_ID),
    ],
)
async def test_order_outside_the_site_is_not_found(order_id: str, site_id: str) -> None:
    pb = FakePocketBase(
        orders=[
            order("order_abc", "paid"),
            order("order_other_site", "paid", site_id=OTHER_SITE),
            order("order_deleted", "paid", deleted_at="2026-11-10T00:00:00Z"),
        ],
        payments=[],
    )

    response = await get_status(build_app(pb), order_id, site_id)

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"
    for value in PII:
        assert value not in response.text


@pytest.mark.parametrize(
    "order_id,site_id", [("order abc", SITE_ID), ("order_abc", 'site"x')]
)
async def test_malformed_ids_are_rejected(order_id: str, site_id: str) -> None:
    pb = FakePocketBase(orders=[order("order_abc", "paid")])

    response = await get_status(build_app(pb), order_id, site_id)

    assert response.status_code == 400
    assert pb.list_calls == []


async def test_polling_every_three_seconds_for_a_minute_is_not_rate_limited() -> None:
    pb = FakePocketBase(orders=[order("order_abc", "pending")], payments=[])
    app = build_app(pb)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        codes = [
            (await client.get(f"/public/sites/{SITE_ID}/orders/order_abc")).status_code
            for _ in range(20)
        ]

    assert codes == [200] * 20


async def _momo_checkout(pb: FakePocketBase, app: FastAPI) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/public/sites/{SITE_ID}/orders",
            json={
                "customer_name": PII[0],
                "customer_phone": PII[1],
                "customer_email": PII[2],
                "shipping_address": PII[3],
                "payment_method": "momo",
                "total": 720_000,
                "items": [{"property_id": "p-ly-gom", "quantity": 1, "unit_price": 1}],
            },
        )
    assert response.status_code == 201, response.text
    return response.json()["order_id"]


def momo_client() -> AsyncMock:
    client = AsyncMock(spec=MomoGatewayClient)
    client.partner_code = SAMPLE_PARTNER_CODE
    client.create_payment.return_value = MomoCreatePaymentResponse(
        partnerCode=SAMPLE_PARTNER_CODE,
        requestId="req_1",
        orderId="ignored",
        amount=720_000,
        responseTime=1700000000000,
        message="Successful.",
        resultCode=0,
        payUrl="https://test-payment.momo.vn/pay",
    )
    return client


@pytest.mark.parametrize(
    "result_code,expected_status,expected_payment",
    [(0, "paid", "completed"), (1006, "failed", "failed")],
)
async def test_ipn_outcome_is_what_the_poll_reads(
    result_code: int, expected_status: str, expected_payment: str
) -> None:
    pb = FakePocketBase(orders=[], order_items=[], payments=[], properties=[])
    app = build_app(pb, momo_client())
    order_id = await _momo_checkout(pb, app)

    before = await get_status(app, order_id)
    assert before.json()["status"] == "pending"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        ipn = await client.post(
            "/public/webhooks/momo/ipn",
            json=make_signed_ipn_payload(
                order_id=order_id, amount=720_000, result_code=result_code
            ),
        )
    assert ipn.status_code == 200, ipn.text

    after = await get_status(app, order_id)
    assert after.status_code == 200
    assert after.json()["status"] == expected_status
    assert after.json()["payment_status"] == expected_payment
    assert_no_pii(after)
