from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.infrastructure.logging import get_logger
from app.infrastructure.momo.client import MomoGatewayClient, MomoGatewayError
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import get_static_pocketbase_client
from app.interface.dto.public_order import (
    PublicOrderCreateRequest,
    PublicOrderResponse,
)
from app.interface.rate_limits import public_submission_limit
from app.interface.route_helpers import validate_id

logger = get_logger("public_orders")

public_order_router = APIRouter(prefix="/public", tags=["Public Orders"])


def get_momo_client() -> MomoGatewayClient:
    return MomoGatewayClient()


@public_order_router.post(
    "/sites/{site_id}/orders",
    dependencies=[Depends(public_submission_limit)],
    response_model=PublicOrderResponse,
    status_code=201,
)
async def create_public_order(
    site_id: str,
    body: PublicOrderCreateRequest,
    pb: PocketBaseClient = Depends(get_static_pocketbase_client),
    momo_client: MomoGatewayClient = Depends(get_momo_client),
) -> PublicOrderResponse:
    validate_id(site_id, "site_id")

    if not body.items:
        raise HTTPException(
            status_code=422,
            detail="An order requires at least one item",
        )

    for item in body.items:
        if item.quantity <= 0:
            raise HTTPException(
                status_code=422,
                detail="Item quantity must be greater than zero",
            )
        if item.unit_price < 0:
            raise HTTPException(
                status_code=422,
                detail="Item unit price cannot be negative",
            )

    if body.total is not None:
        order_total = body.total
    else:
        order_total = sum(int(item.quantity * item.unit_price) for item in body.items)

    if order_total < 1_000:
        raise HTTPException(
            status_code=422,
            detail="Order amount must be at least 1,000 VND",
        )
    if order_total > 50_000_000:
        raise HTTPException(
            status_code=422,
            detail="Order amount must not exceed 50,000,000 VND",
        )

    payment_method = (body.payment_method or "cod").strip().lower()
    if payment_method not in {"momo", "cod", "bank"}:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported payment method: {payment_method}",
        )

    order_id = f"order_{uuid4().hex}"
    order_record = {
        "order_id": order_id,
        "site_id": site_id,
        "customer_name": body.customer_name,
        "customer_email": str(body.customer_email) if body.customer_email else "",
        "customer_phone": body.customer_phone or "",
        "status": "pending",
        "total": order_total,
        "currency": "VND",
        "notes": body.notes or "",
        "metadata": {
            **(body.metadata or {}),
            "shipping_address": body.shipping_address,
            "payment_method": payment_method,
        },
    }
    await pb.create_record("orders", order_record)

    for item in body.items:
        item_id = f"item_{uuid4().hex}"
        item_record = {
            "item_id": item_id,
            "order_id": order_id,
            "property_id": item.property_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "total_price": int(item.quantity * item.unit_price),
            "variation": item.variation or {},
            "metadata": item.metadata or {},
        }
        await pb.create_record("order_items", item_record)

    if payment_method == "momo":
        request_id = f"req_{uuid4().hex}"
        momo_req = {
            "requestId": request_id,
            "orderId": order_id,
            "amount": order_total,
            "orderInfo": f"Order {order_id}",
            "extraData": "",
        }
        try:
            momo_res = await momo_client.create_payment(momo_req)
        except MomoGatewayError as exc:
            logger.error(
                "MoMo payment initiation failed",
                extra={"error": str(exc), "order_id": order_id},
            )
            raise HTTPException(
                status_code=502,
                detail=f"MoMo gateway error: {exc}",
            ) from exc

        payment_id = f"pay_{uuid4().hex}"
        payment_record = {
            "payment_id": payment_id,
            "order_id": order_id,
            "gateway": "momo",
            "method": "momo",
            "status": "pending",
            "request_id": request_id,
            "amount": order_total,
            "currency": "VND",
            "partner_code": getattr(momo_res, "partnerCode", None)
            or getattr(momo_client, "partner_code", ""),
            "raw_payload": momo_res.model_dump()
            if hasattr(momo_res, "model_dump")
            else {},
        }
        await pb.create_record("payments", payment_record)

        return PublicOrderResponse(
            order_id=order_id,
            status="pending",
            total=order_total,
            currency="VND",
            payment_method="momo",
            payment_id=payment_id,
            pay_url=momo_res.payUrl,
            deeplink=momo_res.deeplink,
            qr_code_url=momo_res.qrCodeUrl,
            customer_name=body.customer_name,
            customer_phone=body.customer_phone,
            customer_email=str(body.customer_email) if body.customer_email else None,
        )

    payment_id = f"pay_{uuid4().hex}"
    payment_record = {
        "payment_id": payment_id,
        "order_id": order_id,
        "gateway": payment_method,
        "method": payment_method,
        "status": "pending",
        "amount": order_total,
        "currency": "VND",
        "notes": f"Payment method: {payment_method.upper()}",
    }
    await pb.create_record("payments", payment_record)

    return PublicOrderResponse(
        order_id=order_id,
        status="pending",
        total=order_total,
        currency="VND",
        payment_method=payment_method,
        payment_id=payment_id,
        pay_url=None,
        deeplink=None,
        qr_code_url=None,
        customer_name=body.customer_name,
        customer_phone=body.customer_phone,
        customer_email=str(body.customer_email) if body.customer_email else None,
    )
