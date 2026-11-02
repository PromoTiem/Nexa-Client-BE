import hashlib
import hmac
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import get_settings
from app.infrastructure.logging import get_logger
from app.infrastructure.momo.dto import (
    MomoCreatePaymentRequest,
    MomoCreatePaymentResponse,
    MomoQueryResponse,
)

logger = get_logger("momo")

CANONICAL_IPN_KEYS = (
    "accessKey",
    "amount",
    "extraData",
    "message",
    "orderId",
    "orderInfo",
    "orderType",
    "partnerCode",
    "payType",
    "requestId",
    "responseTime",
    "resultCode",
    "transId",
)


class MomoGatewayError(Exception):
    """Base exception for MoMo gateway operations."""


class MomoGatewayServerError(MomoGatewayError):
    """MoMo upstream server returned a retryable 5xx error."""


class MomoSignatureError(MomoGatewayError):
    """Cryptographic signature validation failure."""


def generate_signature(params: dict[str, Any], secret_key: str) -> str:
    """Compute HMAC SHA256 signature for parameters sorted in ASCII alphabetical order.

    Filters out 'signature' and None values; preserves empty string values.
    Never logs secret_key.
    """
    sorted_items = [
        f"{key}={params[key]}"
        for key in sorted(params.keys())
        if key != "signature" and params[key] is not None
    ]
    raw_signature = "&".join(sorted_items)
    return (
        hmac.new(
            secret_key.encode("utf-8"),
            raw_signature.encode("utf-8"),
            hashlib.sha256,
        )
        .hexdigest()
        .lower()
    )


def verify_signature(
    payload: dict[str, Any],
    secret_key: str,
    access_key: str | None = None,
) -> bool:
    """Verify inbound MoMo HMAC SHA256 signature using constant-time comparison.

    Supports canonical IPN webhook payloads and generic parameter mappings.
    Uses hmac.compare_digest exclusively.
    """
    if (
        not isinstance(payload, dict)
        or not isinstance(secret_key, str)
        or not secret_key
    ):
        return False

    received_signature = payload.get("signature")
    if not received_signature or not isinstance(received_signature, str):
        return False

    effective_access_key = access_key or payload.get("accessKey")

    # If canonical IPN keys are present, test against canonical IPN template
    if "transId" in payload and effective_access_key is not None:
        ipn_params: dict[str, Any] = {"accessKey": effective_access_key}
        for key in CANONICAL_IPN_KEYS:
            if key != "accessKey" and key in payload:
                ipn_params[key] = payload[key]
        expected_sig = generate_signature(ipn_params, secret_key)
        if hmac.compare_digest(expected_sig, received_signature):
            return True

    # Fallback to direct parameter sorting
    direct_params = {
        key: value
        for key, value in payload.items()
        if key != "signature" and value is not None
    }
    if effective_access_key is not None and "accessKey" not in direct_params:
        direct_params["accessKey"] = effective_access_key

    direct_sig = generate_signature(direct_params, secret_key)
    return hmac.compare_digest(direct_sig, received_signature)


class MomoGatewayClient:
    def __init__(
        self,
        endpoint: str | None = None,
        query_endpoint: str | None = None,
        partner_code: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        ipn_url: str | None = None,
        redirect_url: str | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        retry_backoff: float = 0.2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        momo_cfg = settings.momo

        self.endpoint = endpoint or momo_cfg.endpoint
        self.query_endpoint = query_endpoint or momo_cfg.query_endpoint
        self.partner_code = partner_code or momo_cfg.partner_code
        self.access_key = access_key or momo_cfg.access_key
        self.secret_key = secret_key or momo_cfg.secret_key
        self.ipn_url = ipn_url or momo_cfg.ipn_url
        self.redirect_url = redirect_url or momo_cfg.redirect_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._client = client

    async def _post_with_retry(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential_jitter(initial=self.retry_backoff, max=2.0),
            retry=retry_if_exception_type((httpx.RequestError, MomoGatewayServerError)),
            reraise=True,
        ):
            with attempt:
                if self._client is not None:
                    response = await self._client.post(url, json=payload)
                else:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        response = await client.post(url, json=payload)

                if response.status_code >= 500:
                    raise MomoGatewayServerError(
                        f"MoMo upstream error HTTP {response.status_code}: {response.text[:200]}"
                    )

                try:
                    data = response.json()
                    if isinstance(data, dict):
                        return data
                    raise MomoGatewayError(
                        f"MoMo response is not a JSON object: {data}"
                    )
                except Exception as exc:
                    if isinstance(exc, MomoGatewayError):
                        raise
                    raise MomoGatewayError(
                        f"Failed to parse MoMo response JSON: {response.text[:200]}"
                    ) from exc

        raise MomoGatewayError("Max retries exceeded")

    async def create_payment(
        self,
        request_data: MomoCreatePaymentRequest | dict[str, Any],
        secret_key: str | None = None,
        partner_code: str | None = None,
        access_key: str | None = None,
    ) -> MomoCreatePaymentResponse:
        if isinstance(request_data, dict):
            req_dict = dict(request_data)
            if "partnerCode" not in req_dict and (partner_code or self.partner_code):
                req_dict["partnerCode"] = partner_code or self.partner_code
            if "ipnUrl" not in req_dict and self.ipn_url:
                req_dict["ipnUrl"] = self.ipn_url
            if "redirectUrl" not in req_dict and self.redirect_url:
                req_dict["redirectUrl"] = self.redirect_url
            req = MomoCreatePaymentRequest.model_validate(req_dict)
        else:
            req = request_data.model_copy()

        partner_code_val = partner_code or req.partnerCode or self.partner_code
        access_key_val = access_key or self.access_key
        secret_key_val = secret_key or self.secret_key
        ipn_url_val = req.ipnUrl or self.ipn_url
        redirect_url_val = req.redirectUrl or self.redirect_url

        sign_params = {
            "accessKey": access_key_val,
            "amount": req.amount,
            "extraData": req.extraData,
            "ipnUrl": ipn_url_val,
            "orderId": req.orderId,
            "orderInfo": req.orderInfo,
            "partnerCode": partner_code_val,
            "redirectUrl": redirect_url_val,
            "requestId": req.requestId,
            "requestType": req.requestType,
        }
        signature = generate_signature(sign_params, secret_key_val)

        body = {
            "partnerCode": partner_code_val,
            "partnerName": req.partnerName,
            "storeId": req.storeId,
            "requestId": req.requestId,
            "amount": req.amount,
            "orderId": req.orderId,
            "orderInfo": req.orderInfo,
            "redirectUrl": redirect_url_val,
            "ipnUrl": ipn_url_val,
            "lang": req.lang,
            "extraData": req.extraData,
            "requestType": req.requestType,
            "autoCapture": req.autoCapture,
            "signature": signature,
        }

        logger.info(
            "Dispatching MoMo create_payment request",
            extra={
                "order_id": req.orderId,
                "request_id": req.requestId,
                "partner_code": partner_code_val,
            },
        )

        raw_response = await self._post_with_retry(self.endpoint, body)

        if "partnerCode" not in raw_response:
            raw_response["partnerCode"] = partner_code_val
        if "orderId" not in raw_response:
            raw_response["orderId"] = req.orderId
        if "requestId" not in raw_response:
            raw_response["requestId"] = req.requestId
        if "amount" not in raw_response:
            raw_response["amount"] = req.amount
        if "responseTime" not in raw_response:
            raw_response["responseTime"] = 0

        return MomoCreatePaymentResponse.model_validate(raw_response)

    async def query_payment(
        self,
        order_id: str,
        request_id: str,
        secret_key: str | None = None,
        partner_code: str | None = None,
        access_key: str | None = None,
        lang: str = "vi",
    ) -> MomoQueryResponse:
        partner_code_val = partner_code or self.partner_code
        access_key_val = access_key or self.access_key
        secret_key_val = secret_key or self.secret_key

        sign_params = {
            "accessKey": access_key_val,
            "orderId": order_id,
            "partnerCode": partner_code_val,
            "requestId": request_id,
        }
        signature = generate_signature(sign_params, secret_key_val)

        body = {
            "partnerCode": partner_code_val,
            "requestId": request_id,
            "orderId": order_id,
            "signature": signature,
            "lang": lang,
        }

        logger.info(
            "Dispatching MoMo query_payment request",
            extra={
                "order_id": order_id,
                "request_id": request_id,
                "partner_code": partner_code_val,
            },
        )

        raw_response = await self._post_with_retry(self.query_endpoint, body)

        if "partnerCode" not in raw_response:
            raw_response["partnerCode"] = partner_code_val
        if "orderId" not in raw_response:
            raw_response["orderId"] = order_id
        if "requestId" not in raw_response:
            raw_response["requestId"] = request_id

        return MomoQueryResponse.model_validate(raw_response)
