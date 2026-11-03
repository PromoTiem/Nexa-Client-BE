from unittest.mock import patch

import httpx
import pytest
import respx

from app.infrastructure.momo.client import (
    MomoGatewayClient,
    generate_signature,
    verify_signature,
)
from app.infrastructure.momo.dto import (
    MomoCreatePaymentRequest,
    MomoCreatePaymentResponse,
    MomoIpnPayload,
    MomoQueryResponse,
)

SAMPLE_ACCESS_KEY = "SvDmj2cOTYZmQQ3H"
SAMPLE_SECRET_KEY = "PPuDXq1KowPT1ftR8DvlQTHhC03aul17"
SAMPLE_PARTNER_CODE = "MOMOIQA420180417"


class TestMomoSignatureEngine:
    def test_canonical_create_signature_vector(self) -> None:
        """Verify signature generation against canonical MoMo reference vector."""
        params = {
            "accessKey": SAMPLE_ACCESS_KEY,
            "amount": 50000,
            "extraData": "",
            "ipnUrl": "https://callback.url/notify",
            "orderId": "MOMOIQA4201804171636971265214",
            "orderInfo": "Thanh toán qua ví MoMo",
            "partnerCode": SAMPLE_PARTNER_CODE,
            "redirectUrl": "https://momo.vn/return",
            "requestId": "MOMOIQA4201804171636971265214",
            "requestType": "captureWallet",
        }
        # In ASCII sorted order:
        # accessKey, amount, extraData, ipnUrl, orderId, orderInfo, partnerCode, redirectUrl, requestId, requestType
        expected_sig = (
            "7f08bd28142116610de927c4bd29d56289f4765804189e03d9017428d5986aa3"
        )
        sig = generate_signature(params, SAMPLE_SECRET_KEY)
        assert sig == expected_sig

    def test_signature_filters_signature_and_none_values(self) -> None:
        params = {
            "accessKey": SAMPLE_ACCESS_KEY,
            "amount": 10000,
            "signature": "existing_signature_to_ignore",
            "optionalField": None,
            "extraData": "",
        }
        sig1 = generate_signature(params, SAMPLE_SECRET_KEY)
        sig2 = generate_signature(
            {"accessKey": SAMPLE_ACCESS_KEY, "amount": 10000, "extraData": ""},
            SAMPLE_SECRET_KEY,
        )
        assert sig1 == sig2

    def test_signature_preserves_empty_string_values(self) -> None:
        params_empty = {"extraData": "", "partnerCode": "MOMO"}
        sig = generate_signature(params_empty, SAMPLE_SECRET_KEY)
        assert isinstance(sig, str)
        assert len(sig) == 64

    def test_verify_signature_passes_valid_payload(self) -> None:
        payload = {
            "partnerCode": SAMPLE_PARTNER_CODE,
            "orderId": "ORD-12345",
            "requestId": "REQ-12345",
            "amount": 25000,
        }
        sig = generate_signature(payload, SAMPLE_SECRET_KEY)
        payload["signature"] = sig
        assert verify_signature(payload, SAMPLE_SECRET_KEY) is True

    def test_verify_signature_rejects_tampered_amount(self) -> None:
        payload = {
            "partnerCode": SAMPLE_PARTNER_CODE,
            "orderId": "ORD-12345",
            "requestId": "REQ-12345",
            "amount": 25000,
        }
        sig = generate_signature(payload, SAMPLE_SECRET_KEY)
        payload["signature"] = sig
        payload["amount"] = 999999
        assert verify_signature(payload, SAMPLE_SECRET_KEY) is False

    def test_verify_signature_rejects_tampered_signature(self) -> None:
        payload = {
            "partnerCode": SAMPLE_PARTNER_CODE,
            "orderId": "ORD-12345",
            "signature": "0000000000000000000000000000000000000000000000000000000000000000",
        }
        assert verify_signature(payload, SAMPLE_SECRET_KEY) is False

    def test_verify_signature_rejects_missing_signature(self) -> None:
        payload = {"partnerCode": SAMPLE_PARTNER_CODE, "orderId": "ORD-12345"}
        assert verify_signature(payload, SAMPLE_SECRET_KEY) is False

    def test_verify_signature_uses_compare_digest(self) -> None:
        payload = {
            "partnerCode": SAMPLE_PARTNER_CODE,
            "orderId": "ORD-12345",
        }
        sig = generate_signature(payload, SAMPLE_SECRET_KEY)
        payload["signature"] = sig

        with patch("hmac.compare_digest", wraps=lambda a, b: a == b) as mock_compare:
            result = verify_signature(payload, SAMPLE_SECRET_KEY)
            assert result is True
            assert mock_compare.called

    def test_verify_canonical_ipn_payload(self) -> None:
        ipn_data = {
            "partnerCode": SAMPLE_PARTNER_CODE,
            "orderId": "ORD-99999",
            "requestId": "REQ-99999",
            "amount": 100000,
            "orderInfo": "Thanh toan don hang test",
            "orderType": "momo_wallet",
            "transId": 230918239,
            "resultCode": 0,
            "message": "Successful.",
            "payType": "qr",
            "responseTime": 1698000000000,
            "extraData": "",
        }
        sign_params = dict(ipn_data)
        sign_params["accessKey"] = SAMPLE_ACCESS_KEY
        sig = generate_signature(sign_params, SAMPLE_SECRET_KEY)
        ipn_data["signature"] = sig

        ipn_model = MomoIpnPayload.model_validate(ipn_data)
        assert (
            verify_signature(
                ipn_model.model_dump(), SAMPLE_SECRET_KEY, access_key=SAMPLE_ACCESS_KEY
            )
            is True
        )

        # Tampered resultCode should fail
        tampered_data = dict(ipn_data)
        tampered_data["resultCode"] = 49
        assert (
            verify_signature(
                tampered_data, SAMPLE_SECRET_KEY, access_key=SAMPLE_ACCESS_KEY
            )
            is False
        )


class TestMomoGatewayClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_create_payment_success(self) -> None:
        create_route = respx.post(
            "https://test-payment.momo.vn/v2/gateway/api/create"
        ).respond(
            status_code=200,
            json={
                "partnerCode": SAMPLE_PARTNER_CODE,
                "orderId": "ORD-101",
                "requestId": "REQ-101",
                "amount": 50000,
                "responseTime": 1698000001000,
                "message": "Successful.",
                "resultCode": 0,
                "payUrl": "https://test-payment.momo.vn/v2/gateway/pay?t=token123",
                "deeplink": "momo://action=pay&token=token123",
                "qrCodeUrl": "https://test-payment.momo.vn/qr?t=token123",
            },
        )

        client = MomoGatewayClient(
            endpoint="https://test-payment.momo.vn/v2/gateway/api/create",
            partner_code=SAMPLE_PARTNER_CODE,
            access_key=SAMPLE_ACCESS_KEY,
            secret_key=SAMPLE_SECRET_KEY,
            ipn_url="https://site.example.com/api/ipn",
            redirect_url="https://site.example.com/return",
        )

        request_data = MomoCreatePaymentRequest(
            partnerCode=SAMPLE_PARTNER_CODE,
            requestId="REQ-101",
            amount=50000,
            orderId="ORD-101",
            orderInfo="Test payment",
            redirectUrl="https://site.example.com/return",
            ipnUrl="https://site.example.com/api/ipn",
        )

        response = await client.create_payment(request_data)

        assert create_route.called
        assert isinstance(response, MomoCreatePaymentResponse)
        assert response.resultCode == 0
        assert (
            response.payUrl == "https://test-payment.momo.vn/v2/gateway/pay?t=token123"
        )
        assert response.deeplink == "momo://action=pay&token=token123"

        # Check outbound request payload
        sent_body = create_route.calls.last.request.read()
        import json

        payload = json.loads(sent_body.decode("utf-8"))
        assert payload["partnerCode"] == SAMPLE_PARTNER_CODE
        assert payload["orderId"] == "ORD-101"
        assert payload["amount"] == 50000
        assert "signature" in payload
        assert len(payload["signature"]) == 64

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_payment_with_dict_and_overrides(self) -> None:
        custom_partner = "CUSTOM_PARTNER"
        custom_secret = "CUSTOM_SECRET_KEY"
        custom_access = "CUSTOM_ACCESS_KEY"

        create_route = respx.post("https://custom.endpoint/create").respond(
            status_code=200,
            json={
                "partnerCode": custom_partner,
                "orderId": "ORD-202",
                "requestId": "REQ-202",
                "amount": 75000,
                "responseTime": 1698000002000,
                "message": "Successful.",
                "resultCode": 0,
                "payUrl": "https://custom.endpoint/pay",
            },
        )

        client = MomoGatewayClient(
            endpoint="https://custom.endpoint/create",
            partner_code="DEFAULT_PARTNER",
            access_key="DEFAULT_ACCESS",
            secret_key="DEFAULT_SECRET",
        )

        dict_request = {
            "orderId": "ORD-202",
            "requestId": "REQ-202",
            "amount": 75000,
            "orderInfo": "Override test",
            "redirectUrl": "https://custom.com/return",
            "ipnUrl": "https://custom.com/ipn",
        }

        response = await client.create_payment(
            dict_request,
            secret_key=custom_secret,
            partner_code=custom_partner,
            access_key=custom_access,
        )

        assert create_route.called
        assert response.resultCode == 0
        assert response.partnerCode == custom_partner

    @pytest.mark.asyncio
    @respx.mock
    async def test_query_payment_success(self) -> None:
        query_route = respx.post(
            "https://test-payment.momo.vn/v2/gateway/api/query"
        ).respond(
            status_code=200,
            json={
                "partnerCode": SAMPLE_PARTNER_CODE,
                "orderId": "ORD-303",
                "requestId": "REQ-303",
                "extraData": "",
                "amount": 120000,
                "transId": 987654321,
                "payType": "momo_wallet",
                "resultCode": 0,
                "message": "Giao dich thanh cong.",
                "responseTime": 1698000003000,
            },
        )

        client = MomoGatewayClient(
            query_endpoint="https://test-payment.momo.vn/v2/gateway/api/query",
            partner_code=SAMPLE_PARTNER_CODE,
            access_key=SAMPLE_ACCESS_KEY,
            secret_key=SAMPLE_SECRET_KEY,
        )

        response = await client.query_payment(order_id="ORD-303", request_id="REQ-303")

        assert query_route.called
        assert isinstance(response, MomoQueryResponse)
        assert response.resultCode == 0
        assert response.transId == 987654321
        assert response.amount == 120000

        # Verify query signature was formed with accessKey, orderId, partnerCode, requestId
        import json

        sent_body = json.loads(query_route.calls.last.request.read().decode("utf-8"))
        assert sent_body["orderId"] == "ORD-303"
        assert sent_body["requestId"] == "REQ-303"
        expected_sig = generate_signature(
            {
                "accessKey": SAMPLE_ACCESS_KEY,
                "orderId": "ORD-303",
                "partnerCode": SAMPLE_PARTNER_CODE,
                "requestId": "REQ-303",
            },
            SAMPLE_SECRET_KEY,
        )
        assert sent_body["signature"] == expected_sig

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_on_server_error_recovers(self) -> None:
        route = respx.post("https://test-payment.momo.vn/v2/gateway/api/create")
        route.side_effect = [
            httpx.Response(502, text="Bad Gateway"),
            httpx.Response(
                200,
                json={
                    "partnerCode": SAMPLE_PARTNER_CODE,
                    "orderId": "ORD-404",
                    "requestId": "REQ-404",
                    "amount": 30000,
                    "responseTime": 1698000004000,
                    "message": "Successful after retry.",
                    "resultCode": 0,
                    "payUrl": "https://test.momo.vn/pay",
                },
            ),
        ]

        client = MomoGatewayClient(
            endpoint="https://test-payment.momo.vn/v2/gateway/api/create",
            partner_code=SAMPLE_PARTNER_CODE,
            access_key=SAMPLE_ACCESS_KEY,
            secret_key=SAMPLE_SECRET_KEY,
            ipn_url="https://site.example.com/ipn",
            redirect_url="https://site.example.com/return",
            retry_backoff=0.01,
        )

        req = MomoCreatePaymentRequest(
            partnerCode=SAMPLE_PARTNER_CODE,
            requestId="REQ-404",
            amount=30000,
            orderId="ORD-404",
            orderInfo="Retry test",
            redirectUrl="https://site.example.com/return",
            ipnUrl="https://site.example.com/ipn",
        )

        response = await client.create_payment(req)
        assert response.resultCode == 0
        assert route.call_count == 2
