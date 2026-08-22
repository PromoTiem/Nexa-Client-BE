import json

import httpx
import pytest
import respx
from fastapi import HTTPException

from app.infrastructure.pocketbase.client import PocketBaseClient, create_static_pb_client

PB_BASE = "https://test.example.com"
COLLECTION = "users"
AUTH_URL = (
    f"{PB_BASE}/api/collections/{COLLECTION}/auth-with-password"
)

TEST_IDENTITY = "client@example.com"
TEST_PASSWORD = "client123456"

MOCK_PB_PAYLOAD = {
    "token": "eyJhbGciOiJIUzI1NiJ9.test_token",
    "record": {
        "id": "abc123",
        "collectionId": "d2972397d45614e",
        "collectionName": "users",
        "created": "2022-06-24 06:24:18.434Z",
        "updated": "2022-06-24 06:24:18.889Z",
        "email": TEST_IDENTITY,
        "verified": True,
        "emailVisibility": True,
        "tenant_id": "tenant_abc",
        "role": "admin",
    },
}


class TestPocketBaseClientAuthWithPassword:
    @respx.mock
    async def test_success_returns_token_and_record(self):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(200, json=MOCK_PB_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        result = await client.auth_with_password(
            collection=COLLECTION,
            identity=TEST_IDENTITY,
            password=TEST_PASSWORD,
        )

        assert result["token"] == MOCK_PB_PAYLOAD["token"]
        assert result["record"]["email"] == TEST_IDENTITY

    @respx.mock
    async def test_invalid_credentials_raises_401(self):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(
                400, json={"message": "Failed to authenticate."}
            )
        )
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.auth_with_password(
                collection=COLLECTION,
                identity="wrong@example.com",
                password="wrongpass",
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid credentials"

    @respx.mock
    async def test_collection_not_found_raises_404(self):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(404)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.auth_with_password(
                collection=COLLECTION,
                identity=TEST_IDENTITY,
                password=TEST_PASSWORD,
            )

        assert exc_info.value.status_code == 404
        assert "404" in exc_info.value.detail

    @respx.mock
    async def test_server_error_propagates_status_code(self):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(500)
        )
        client = PocketBaseClient(base_url=PB_BASE, max_retries=1)

        with pytest.raises(HTTPException) as exc_info:
            await client.auth_with_password(
                collection=COLLECTION,
                identity=TEST_IDENTITY,
                password=TEST_PASSWORD,
            )

        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_identity_field_sent_in_payload(self):
        route = respx.post(AUTH_URL).mock(
            return_value=httpx.Response(200, json=MOCK_PB_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        await client.auth_with_password(
            collection=COLLECTION,
            identity=TEST_IDENTITY,
            password=TEST_PASSWORD,
            identity_field="email",
        )

        body = json.loads(route.calls.last.request.content)
        assert body["identityField"] == "email"

    @respx.mock
    async def test_identity_field_omitted_when_none(self):
        route = respx.post(AUTH_URL).mock(
            return_value=httpx.Response(200, json=MOCK_PB_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        await client.auth_with_password(
            collection=COLLECTION,
            identity=TEST_IDENTITY,
            password=TEST_PASSWORD,
            identity_field=None,
        )

        body = json.loads(route.calls.last.request.content)
        assert "identityField" not in body

    @respx.mock
    async def test_base_url_trailing_slash_is_normalized(self):
        url_with_slash = f"{PB_BASE}/"
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(200, json=MOCK_PB_PAYLOAD)
        )
        client = PocketBaseClient(base_url=url_with_slash)

        result = await client.auth_with_password(
            collection=COLLECTION,
            identity=TEST_IDENTITY,
            password=TEST_PASSWORD,
        )

        assert result["token"] == MOCK_PB_PAYLOAD["token"]


REFRESH_URL = (
    f"{PB_BASE}/api/collections/{COLLECTION}/auth-refresh"
)
SAMPLE_TOKEN = "eyJhbGciOiJIUzI1NiJ9.test_token"


class TestPocketBaseClientAuthRefresh:
    @respx.mock
    async def test_success_returns_refreshed_token_and_record(self):
        respx.post(REFRESH_URL).mock(
            return_value=httpx.Response(200, json=MOCK_PB_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        result = await client.auth_refresh(
            collection=COLLECTION,
            token=SAMPLE_TOKEN,
        )

        assert result["token"] == MOCK_PB_PAYLOAD["token"]
        assert result["record"]["email"] == TEST_IDENTITY

    @respx.mock
    async def test_token_sent_in_authorization_header(self):
        route = respx.post(REFRESH_URL).mock(
            return_value=httpx.Response(200, json=MOCK_PB_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        await client.auth_refresh(
            collection=COLLECTION,
            token=SAMPLE_TOKEN,
        )

        sent_auth = route.calls.last.request.headers["authorization"]
        assert sent_auth == SAMPLE_TOKEN

    @respx.mock
    async def test_invalid_token_raises_401(self):
        respx.post(REFRESH_URL).mock(
            return_value=httpx.Response(401)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.auth_refresh(
                collection=COLLECTION,
                token="expired.token.here",
            )

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    @respx.mock
    async def test_collection_not_found_raises_404(self):
        respx.post(REFRESH_URL).mock(
            return_value=httpx.Response(404)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.auth_refresh(
                collection=COLLECTION,
                token=SAMPLE_TOKEN,
            )

        assert exc_info.value.status_code == 404
        assert "404" in exc_info.value.detail

    @respx.mock
    async def test_server_error_propagates_status_code(self):
        respx.post(REFRESH_URL).mock(
            return_value=httpx.Response(500)
        )
        client = PocketBaseClient(base_url=PB_BASE, max_retries=1)

        with pytest.raises(HTTPException) as exc_info:
            await client.auth_refresh(
                collection=COLLECTION,
                token=SAMPLE_TOKEN,
            )

        assert exc_info.value.status_code == 500


TENANTS_COLLECTION = "tenants"
LIST_URL = f"{PB_BASE}/api/collections/{TENANTS_COLLECTION}/records"
SAMPLE_RECORD_ID = "rec_tenant_001"
RECORD_URL = f"{LIST_URL}/{SAMPLE_RECORD_ID}"

MOCK_TENANT_RECORD = {
    "id": SAMPLE_RECORD_ID,
    "tenant_id": "tenant_abc",
    "name": "Tenant ABC",
    "plan": "basic",
    "status": "active",
    "created_at": "2026-06-01T00:00:00Z",
    "updated_at": "2026-06-01T00:00:00Z",
    "created_by": "user_001",
    "updated_by": "user_001",
}

MOCK_LIST_PAYLOAD = {
    "page": 1,
    "perPage": 50,
    "totalItems": 1,
    "totalPages": 1,
    "items": [MOCK_TENANT_RECORD],
}


class TestPocketBaseClientListRecords:
    @respx.mock
    async def test_success_returns_items(self):
        respx.get(LIST_URL).mock(
            return_value=httpx.Response(200, json=MOCK_LIST_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        result = await client.list_records(
            collection=TENANTS_COLLECTION, token=SAMPLE_TOKEN
        )

        assert result["totalItems"] == 1
        assert result["items"][0]["tenant_id"] == "tenant_abc"

    @respx.mock
    async def test_filter_and_sort_forwarded_as_params(self):
        route = respx.get(LIST_URL).mock(
            return_value=httpx.Response(200, json=MOCK_LIST_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        await client.list_records(
            collection=TENANTS_COLLECTION,
            token=SAMPLE_TOKEN,
            filter='tenant_id="tenant_abc"',
            sort="-created_at",
            page=2,
            per_page=10,
        )

        params = dict(route.calls.last.request.url.params)
        assert params["filter"] == 'tenant_id="tenant_abc"'
        assert params["sort"] == "-created_at"
        assert params["page"] == "2"
        assert params["perPage"] == "10"

    @respx.mock
    async def test_token_sent_in_authorization_header(self):
        route = respx.get(LIST_URL).mock(
            return_value=httpx.Response(200, json=MOCK_LIST_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        await client.list_records(
            collection=TENANTS_COLLECTION, token=SAMPLE_TOKEN
        )

        assert route.calls.last.request.headers["Authorization"] == SAMPLE_TOKEN

    @respx.mock
    async def test_invalid_token_raises_401(self):
        respx.get(LIST_URL).mock(return_value=httpx.Response(401))
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.list_records(
                collection=TENANTS_COLLECTION, token="bad.token"
            )

        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_unknown_collection_raises_404(self):
        respx.get(LIST_URL).mock(return_value=httpx.Response(404))
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.list_records(
                collection=TENANTS_COLLECTION, token=SAMPLE_TOKEN
            )

        assert exc_info.value.status_code == 404


class TestPocketBaseClientCollectionList:
    @respx.mock
    async def test_collection_list_calls_list_records(self):
        respx.get(LIST_URL).mock(
            return_value=httpx.Response(200, json=MOCK_LIST_PAYLOAD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        result = await client.collection_list(
            collection=TENANTS_COLLECTION,
            token=SAMPLE_TOKEN,
            filter_expr='status="active"',
            sort="-created",
            page=1,
            per_page=30,
        )

        assert result["totalItems"] == 1


class TestPocketBaseClientFindOneByFilter:
    @respx.mock
    async def test_returns_first_matching_record(self):
        respx.get(LIST_URL).mock(
            return_value=httpx.Response(
                200,
                json={**MOCK_LIST_PAYLOAD, "perPage": 1},
            )
        )
        client = PocketBaseClient(base_url=PB_BASE)

        record = await client.find_one_by_filter(
            collection=TENANTS_COLLECTION,
            filter_expr='tenant_id="tenant_abc"',
            token=SAMPLE_TOKEN,
        )

        assert record["id"] == SAMPLE_RECORD_ID

    @respx.mock
    async def test_no_match_raises_404(self):
        respx.get(LIST_URL).mock(
            return_value=httpx.Response(
                200,
                json={"page": 1, "perPage": 1, "totalItems": 0,
                      "totalPages": 0, "items": []},
            )
        )
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.find_one_by_filter(
                collection=TENANTS_COLLECTION,
                filter_expr='tenant_id="missing"',
                token=SAMPLE_TOKEN,
            )

        assert exc_info.value.status_code == 404


class TestPocketBaseClientCreateRecord:
    @respx.mock
    async def test_success_returns_created_record(self):
        respx.post(LIST_URL).mock(
            return_value=httpx.Response(200, json=MOCK_TENANT_RECORD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        result = await client.create_record(
            collection=TENANTS_COLLECTION,
            data={"tenant_id": "tenant_abc", "name": "Tenant ABC"},
            token=SAMPLE_TOKEN,
        )

        assert result["id"] == SAMPLE_RECORD_ID

    @respx.mock
    async def test_payload_forwarded_as_json_body(self):
        route = respx.post(LIST_URL).mock(
            return_value=httpx.Response(200, json=MOCK_TENANT_RECORD)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        payload = {"tenant_id": "tenant_abc", "name": "My Tenant"}
        await client.create_record(
            collection=TENANTS_COLLECTION, data=payload, token=SAMPLE_TOKEN,
            user_id="user_001",
        )

        body = json.loads(route.calls.last.request.content)
        assert body["tenant_id"] == "tenant_abc"
        assert body["name"] == "My Tenant"
        assert "created_at" in body
        assert "updated_at" in body
        assert body["created_by"] == "user_001"
        assert body["updated_by"] == "user_001"

    @respx.mock
    async def test_validation_error_raises_400(self):
        respx.post(LIST_URL).mock(
            return_value=httpx.Response(
                400, json={"message": "tenant_id is required"}
            )
        )
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.create_record(
                collection=TENANTS_COLLECTION, data={}, token=SAMPLE_TOKEN
            )

        assert exc_info.value.status_code == 400
        assert "tenant_id is required" in exc_info.value.detail

    @respx.mock
    async def test_unauthorized_raises_401(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(401))
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.create_record(
                collection=TENANTS_COLLECTION, data={}, token="bad.token"
            )

        assert exc_info.value.status_code == 401


class TestPocketBaseClientUpdateRecord:
    @respx.mock
    async def test_success_returns_updated_record(self):
        updated = {**MOCK_TENANT_RECORD, "name": "Updated Tenant"}
        respx.patch(RECORD_URL).mock(
            return_value=httpx.Response(200, json=updated)
        )
        client = PocketBaseClient(base_url=PB_BASE)

        result = await client.update_record(
            collection=TENANTS_COLLECTION,
            record_id=SAMPLE_RECORD_ID,
            data={"name": "Updated Tenant"},
            token=SAMPLE_TOKEN,
        )

        assert result["name"] == "Updated Tenant"

    @respx.mock
    async def test_record_not_found_raises_404(self):
        respx.patch(RECORD_URL).mock(return_value=httpx.Response(404))
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.update_record(
                collection=TENANTS_COLLECTION,
                record_id=SAMPLE_RECORD_ID,
                data={"name": "x"},
                token=SAMPLE_TOKEN,
            )

        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_unauthorized_raises_401(self):
        respx.patch(RECORD_URL).mock(return_value=httpx.Response(401))
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.update_record(
                collection=TENANTS_COLLECTION,
                record_id=SAMPLE_RECORD_ID,
                data={},
                token="bad.token",
            )

        assert exc_info.value.status_code == 401


class TestPocketBaseClientDeleteRecord:
    @respx.mock
    async def test_success_returns_none(self):
        respx.delete(RECORD_URL).mock(return_value=httpx.Response(204))
        client = PocketBaseClient(base_url=PB_BASE)

        result = await client.delete_record(
            collection=TENANTS_COLLECTION,
            record_id=SAMPLE_RECORD_ID,
            token=SAMPLE_TOKEN,
        )

        assert result is None

    @respx.mock
    async def test_record_not_found_raises_404(self):
        respx.delete(RECORD_URL).mock(return_value=httpx.Response(404))
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.delete_record(
                collection=TENANTS_COLLECTION,
                record_id=SAMPLE_RECORD_ID,
                token=SAMPLE_TOKEN,
            )

        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_unauthorized_raises_401(self):
        respx.delete(RECORD_URL).mock(return_value=httpx.Response(401))
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.delete_record(
                collection=TENANTS_COLLECTION,
                record_id=SAMPLE_RECORD_ID,
                token="bad.token",
            )

        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_forbidden_raises_403(self):
        respx.delete(RECORD_URL).mock(return_value=httpx.Response(403))
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            await client.delete_record(
                collection=TENANTS_COLLECTION,
                record_id=SAMPLE_RECORD_ID,
                token=SAMPLE_TOKEN,
            )

        assert exc_info.value.status_code == 403


class TestPocketBaseClientRetry:
    @respx.mock
    async def test_retries_on_5xx_then_succeeds(self):
        route = respx.post(AUTH_URL)
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200, json=MOCK_PB_PAYLOAD),
        ]
        client = PocketBaseClient(
            base_url=PB_BASE, max_retries=3, retry_backoff=0.01
        )

        result = await client.auth_with_password(
            collection=COLLECTION,
            identity=TEST_IDENTITY,
            password=TEST_PASSWORD,
        )

        assert result["token"] == MOCK_PB_PAYLOAD["token"]
        assert route.call_count == 3

    @respx.mock
    async def test_retries_exhausted_raises_5xx(self):
        route = respx.post(AUTH_URL)
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
        ]
        client = PocketBaseClient(
            base_url=PB_BASE, max_retries=3, retry_backoff=0.01
        )

        with pytest.raises(HTTPException) as exc_info:
            await client.auth_with_password(
                collection=COLLECTION,
                identity=TEST_IDENTITY,
                password=TEST_PASSWORD,
            )

        assert exc_info.value.status_code == 500
        assert route.call_count == 3

    @respx.mock
    async def test_no_retry_on_4xx(self):
        route = respx.post(AUTH_URL)
        route.mock(return_value=httpx.Response(400))
        client = PocketBaseClient(
            base_url=PB_BASE, max_retries=3, retry_backoff=0.01
        )

        with pytest.raises(HTTPException) as exc_info:
            await client.auth_with_password(
                collection=COLLECTION,
                identity="wrong@example.com",
                password="wrongpass",
            )

        assert exc_info.value.status_code == 401
        assert route.call_count == 1

    @respx.mock
    async def test_retries_on_timeout_then_succeeds(self):
        route = respx.post(AUTH_URL)
        route.side_effect = [
            httpx.ReadTimeout("Connection timed out"),
            httpx.Response(200, json=MOCK_PB_PAYLOAD),
        ]
        client = PocketBaseClient(
            base_url=PB_BASE, max_retries=3, retry_backoff=0.01
        )

        result = await client.auth_with_password(
            collection=COLLECTION,
            identity=TEST_IDENTITY,
            password=TEST_PASSWORD,
        )

        assert result["token"] == MOCK_PB_PAYLOAD["token"]
        assert route.call_count == 2


class TestPocketBaseClientAuthHeaders:
    def test_raises_401_when_no_token_and_no_static_token(self):
        client = PocketBaseClient(base_url=PB_BASE)

        with pytest.raises(HTTPException) as exc_info:
            client._get_auth_headers(token=None)

        assert exc_info.value.status_code == 401
        assert "No token provided" in exc_info.value.detail

    def test_uses_static_token_when_no_token_provided(self):
        client = PocketBaseClient(
            base_url=PB_BASE, static_token="static.val"
        )

        headers = client._get_auth_headers(token=None)

        assert headers == {"x_api_be_token": "static.val"}

    def test_uses_explicit_token_over_static_token(self):
        client = PocketBaseClient(
            base_url=PB_BASE, static_token="static.val"
        )

        headers = client._get_auth_headers(token="bearer mytoken")

        assert headers == {"Authorization": "bearer mytoken"}


class TestCreateStaticPbClient:
    def test_raises_valueerror_when_missing_params(self):
        with pytest.raises(ValueError, match="base_url and static_token"):
            create_static_pb_client()

    def test_raises_valueerror_when_only_base_url(self):
        with pytest.raises(ValueError, match="base_url and static_token"):
            create_static_pb_client(base_url="http://localhost")

    def test_raises_valueerror_when_only_token(self):
        with pytest.raises(ValueError, match="base_url and static_token"):
            create_static_pb_client(static_token="tok")

    def test_creates_client_with_explicit_params(self):
        client = create_static_pb_client(
            base_url="http://pb:8090",
            static_token="mytoken",
        )
        assert isinstance(client, PocketBaseClient)

    def test_creates_client_from_settings(self):
        class FakeSettings:
            pocketbase_url = "http://pb:8090"
            pocketbase_timeout = 5.0
            pocketbase_max_retries = 2
            pocketbase_retry_backoff = 0.1

        client = create_static_pb_client(static_token="settings_token", settings=FakeSettings())
        assert isinstance(client, PocketBaseClient)
