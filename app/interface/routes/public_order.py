from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.application.services.ecommerce_pricing import (
    OrderTotalMismatchError,
    UnknownProductError,
    price_order,
)
from app.config import Settings, get_settings
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


def momo_checkout_configured(settings: Settings) -> bool:
    """A usable MoMo checkout needs the full round trip, not just a partner code.

    Without the IPN URL MoMo cannot confirm the payment, and without the
    redirect URL the shopper never returns to the storefront.
    """
    momo = settings.momo
    return bool(
        momo.enabled
        and momo.partner_code
        and momo.access_key
        and momo.secret_key
        and momo.ipn_url
        and momo.redirect_url
    )


async def record_failed_momo_attempt(
    pb: PocketBaseClient,
    *,
    order_record_id: str | None,
    order_id: str,
    payment_id: str,
    request_id: str,
    amount: int,
    partner_code: str,
    raw_payload: dict[str, object],
    note: str,
) -> None:
    """Persist a rejected attempt and cancel the order that can no longer be paid.

    Audit writes must never hide the gateway error from the caller, so failures
    here are logged and swallowed.
    """
    try:
        await pb.create_record(
            "payments",
            {
                "payment_id": payment_id,
                "order_id": order_id,
                "gateway": "momo",
                "method": "momo",
                "status": "failed",
                "request_id": request_id,
                "amount": amount,
                "currency": "VND",
                "partner_code": partner_code,
                "raw_payload": raw_payload,
                "notes": note,
            },
        )
    except Exception as exc:
        logger.error(
            "Failed to record rejected MoMo payment",
            extra={"order_id": order_id, "error": str(exc)},
        )

    if not order_record_id:
        return
    try:
        await pb.update_record("orders", order_record_id, {"status": "cancelled"})
    except Exception as exc:
        logger.error(
            "Failed to cancel rejected MoMo order",
            extra={"order_id": order_id, "error": str(exc)},
        )


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
    settings: Settings = Depends(get_settings),
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
        if body.total < 1_000:
            raise HTTPException(
                status_code=422,
                detail="Order amount must be at least 1,000 VND",
            )
        if body.total > 50_000_000:
            raise HTTPException(
                status_code=422,
                detail="Order amount must not exceed 50,000,000 VND",
            )

    try:
        pricing = price_order(
            ((item.property_id, item.quantity) for item in body.items),
            prices=settings.ecommerce.prices,
            free_shipping_threshold=settings.ecommerce.free_shipping_threshold,
            shipping_fee=settings.ecommerce.shipping_fee,
            requested_total=body.total,
        )
    except UnknownProductError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown product: {exc.product_id}",
        ) from exc
    except OrderTotalMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail="Order total does not match current prices. Please refresh the cart.",
        ) from exc

    order_total = pricing.total
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
    if payment_method == "momo" and not momo_checkout_configured(settings):
        logger.warning(
            "MoMo checkout is disabled or incomplete",
            extra={"site_id": site_id},
        )
        raise HTTPException(
            status_code=503,
            detail="MoMo payments are not available",
        )

    order_id = f"order_{uuid4().hex}"
    order_payload = {
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
            "subtotal": pricing.subtotal,
            "shipping_fee": pricing.shipping_fee,
        },
    }
    created_order = await pb.create_record("orders", order_payload)
    order_record_id = (
        created_order.get("id") if isinstance(created_order, dict) else None
    )

    for item, priced in zip(body.items, pricing.lines, strict=True):
        item_id = f"item_{uuid4().hex}"
        item_record = {
            "item_id": item_id,
            "order_id": order_id,
            "property_id": priced.product_id,
            "quantity": priced.quantity,
            "unit_price": priced.unit_price,
            "total_price": priced.total_price,
            "variation": item.variation or {},
            "metadata": item.metadata or {},
        }
        await pb.create_record("order_items", item_record)

    if payment_method == "momo":
        request_id = f"req_{uuid4().hex}"
        payment_id = f"pay_{uuid4().hex}"
        partner_code = getattr(momo_client, "partner_code", "") or ""
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
            await record_failed_momo_attempt(
                pb,
                order_record_id=order_record_id,
                order_id=order_id,
                payment_id=payment_id,
                request_id=request_id,
                amount=order_total,
                partner_code=partner_code,
                raw_payload={},
                note="MoMo gateway error",
            )
            raise HTTPException(
                status_code=502,
                detail="MoMo payment could not be initiated",
            ) from exc
        except Exception as exc:
            logger.exception(
                "Unexpected MoMo payment initiation failure",
                extra={"error": str(exc), "order_id": order_id},
            )
            await record_failed_momo_attempt(
                pb,
                order_record_id=order_record_id,
                order_id=order_id,
                payment_id=payment_id,
                request_id=request_id,
                amount=order_total,
                partner_code=partner_code,
                raw_payload={},
                note="Unexpected MoMo gateway error",
            )
            raise

        raw_payload = momo_res.model_dump() if hasattr(momo_res, "model_dump") else {}
        if momo_res.resultCode != 0 or not momo_res.payUrl:
            logger.warning(
                "MoMo rejected payment initiation",
                extra={
                    "order_id": order_id,
                    "result_code": momo_res.resultCode,
                },
            )
            await record_failed_momo_attempt(
                pb,
                order_record_id=order_record_id,
                order_id=order_id,
                payment_id=payment_id,
                request_id=request_id,
                amount=order_total,
                partner_code=partner_code,
                raw_payload=raw_payload,
                note=f"MoMo resultCode {momo_res.resultCode}",
            )
            raise HTTPException(
                status_code=502,
                detail="MoMo payment could not be initiated",
            )

        payment_record = {
            "payment_id": payment_id,
            "order_id": order_id,
            "gateway": "momo",
            "method": "momo",
            "status": "pending",
            "request_id": request_id,
            "amount": order_total,
            "currency": "VND",
            "partner_code": momo_res.partnerCode or partner_code,
            "raw_payload": raw_payload,
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
