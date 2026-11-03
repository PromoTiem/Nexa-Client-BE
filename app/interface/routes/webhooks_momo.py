from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.infrastructure.logging import get_logger
from app.infrastructure.momo import verify_signature
from app.infrastructure.momo.dto import MomoIpnPayload
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value
from app.interface.dependencies import get_static_pocketbase_client

logger = get_logger("webhooks_momo")

momo_webhook_router = APIRouter(prefix="/public/webhooks/momo", tags=["MoMo Webhooks"])


@momo_webhook_router.post("/ipn", status_code=200)
async def handle_momo_ipn(
    payload: dict[str, Any] | MomoIpnPayload,
    pb: PocketBaseClient = Depends(get_static_pocketbase_client),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if isinstance(payload, BaseModel):
        payload_dict = payload.model_dump()
    elif isinstance(payload, dict):
        payload_dict = dict(payload)
    elif hasattr(payload, "model_dump"):
        payload_dict = payload.model_dump()
    else:
        payload_dict = dict(payload)

    secret_key = settings.momo.secret_key
    access_key = settings.momo.access_key or payload_dict.get("accessKey")

    if not verify_signature(payload_dict, secret_key, access_key):
        logger.warning(
            "MoMo IPN signature verification failed",
            extra={"order_id": payload_dict.get("orderId")},
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid HMAC signature",
        )

    order_id = payload_dict.get("orderId")
    if not order_id:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        order = await pb.find_one_by_filter(
            "orders",
            f'order_id="{sanitize_filter_value(str(order_id))}"',
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Order not found") from exc
        raise
    except Exception as exc:
        logger.error(
            "Failed to find order during MoMo IPN processing",
            extra={"order_id": order_id, "error": str(exc)},
        )
        raise HTTPException(status_code=404, detail="Order not found") from exc

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        payload_amount = int(payload_dict["amount"])
        order_total = int(order["total"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Amount mismatch")

    if payload_amount != order_total:
        logger.warning(
            "MoMo IPN amount mismatch",
            extra={
                "order_id": order_id,
                "payload_amount": payload_amount,
                "order_total": order_total,
            },
        )
        raise HTTPException(status_code=400, detail="Amount mismatch")

    matching_payment = None
    try:
        payments_res = await pb.list_records(
            "payments",
            filter=f'order_id="{sanitize_filter_value(str(order_id))}"',
            sort="-created_at",
            page=1,
            per_page=1,
        )
        items = payments_res.get("items", []) if isinstance(payments_res, dict) else []
        if items:
            matching_payment = items[0]
    except Exception as exc:
        logger.warning(
            "Failed to list payments for order",
            extra={"order_id": order_id, "error": str(exc)},
        )
        try:
            matching_payment = await pb.find_one_by_filter(
                "payments",
                f'order_id="{sanitize_filter_value(str(order_id))}"',
            )
        except Exception:
            matching_payment = None

    is_order_paid = order.get("status") == "paid"
    is_payment_completed = (
        matching_payment is not None and matching_payment.get("status") == "completed"
    )

    if is_order_paid or is_payment_completed:
        logger.info(
            "MoMo IPN idempotency check passed (order_paid=%s, payment_completed=%s); no-op",
            is_order_paid,
            is_payment_completed,
            extra={"order_id": order_id},
        )
        return {"resultCode": 0, "message": "Received IPN successfully"}

    try:
        result_code = int(payload_dict.get("resultCode", -1))
    except (ValueError, TypeError):
        result_code = -1

    if result_code == 0:
        payment_update = {
            "status": "completed",
            "trans_id": str(payload_dict.get("transId", "")),
            "pay_type": payload_dict.get("payType", ""),
            "raw_payload": payload_dict,
        }
        if matching_payment:
            await pb.update_record("payments", matching_payment["id"], payment_update)
        else:
            payment_record = {
                "payment_id": f"pay_{uuid4().hex}",
                "order_id": order_id,
                "gateway": "momo",
                "method": "momo",
                "amount": order_total,
                "currency": "VND",
                **payment_update,
            }
            await pb.create_record("payments", payment_record)

        await pb.update_record("orders", order["id"], {"status": "paid"})
        logger.info(
            "MoMo payment completed successfully",
            extra={
                "order_id": order_id,
                "trans_id": payment_update["trans_id"],
            },
        )
        return {"resultCode": 0, "message": "Received IPN successfully"}

    payment_update = {
        "status": "failed",
        "raw_payload": payload_dict,
    }
    if matching_payment:
        await pb.update_record("payments", matching_payment["id"], payment_update)
    else:
        payment_record = {
            "payment_id": f"pay_{uuid4().hex}",
            "order_id": order_id,
            "gateway": "momo",
            "method": "momo",
            "amount": order_total,
            "currency": "VND",
            **payment_update,
        }
        await pb.create_record("payments", payment_record)

    logger.warning(
        "MoMo payment failed or cancelled; order remains pending",
        extra={"order_id": order_id, "result_code": result_code},
    )
    return {"resultCode": 0, "message": "Received IPN successfully"}
