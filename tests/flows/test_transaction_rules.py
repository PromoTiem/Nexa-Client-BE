"""Validate the proposed read boundary using real ordinary-user PB tokens."""

import httpx
from fastapi import FastAPI

from app.config import get_settings
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    get_pocketbase_client,
    get_static_pocketbase_client,
)
from app.interface.routes.transactional import router
from scripts.transaction_schema_candidate import candidate
from tests.flows.test_transaction_flow import database  # noqa: F401


async def test_real_user_read_rules(database):  # noqa: F811
    base, admin, _ = database
    async with httpx.AsyncClient(
        base_url=base, headers={"Authorization": admin}
    ) as client:

        async def post(path, payload):
            response = await client.post(path, json=payload)
            response.raise_for_status()
            return response.json()

        # The flow fixture stores a text tenant relation; replace only the empty
        # fixture definition before seeding these standalone collections.
        tenant_schema = (await client.get("/api/collections/tenants")).json()
        site_schema = (await client.get("/api/collections/sites")).json()
        for field in site_schema["fields"]:
            if field["name"] == "tenant_id":
                field.clear()
                field.update(
                    name="tenant_id",
                    type="relation",
                    collectionId=tenant_schema["id"],
                    maxSelect=1,
                    cascadeDelete=False,
                )
        response = await client.patch("/api/collections/sites", json=site_schema)
        assert response.is_success, response.text
        response = await client.patch(
            "/api/collections/users",
            json={
                "fields": [
                    {"name": "tenant_id", "type": "text"},
                    {"name": "role", "type": "text"},
                    {"name": "status", "type": "text"},
                ]
            },
        )
        assert response.is_success, response.text
        identities = []
        for suffix in ("a", "b"):
            tenant = await post(
                "/api/collections/tenants/records", {"tenant_id": "tenant_" + suffix}
            )
            await post(
                "/api/collections/sites/records",
                {"site_id": "site_" + suffix, "tenant_id": tenant["id"], "config": {}},
            )
            order = await post(
                "/api/collections/orders/records",
                {
                    "order_id": "order_" + suffix,
                    "site_id": "site_" + suffix,
                    "status": "pending",
                    "total": 1,
                    "currency": "USD",
                },
            )
            await post(
                "/api/collections/users/records",
                {
                    "email": suffix + "@example.test",
                    "password": "Disposable-password-123",
                    "passwordConfirm": "Disposable-password-123",
                    "tenant_id": "tenant_" + suffix,
                    "role": "owner",
                    "status": "active",
                },
            )
            auth = await post(
                "/api/collections/users/auth-with-password",
                {
                    "identity": suffix + "@example.test",
                    "password": "Disposable-password-123",
                },
            )
            identities.append((auth["token"], order))
        original = (await client.get("/api/collections/orders")).json()
        response = await client.patch(
            "/api/collections/orders", json=candidate(original)
        )
        response.raise_for_status()
        for index, (token, order) in enumerate(identities):
            headers = {"Authorization": token}
            result = await client.get(
                "/api/collections/orders/records", headers=headers
            )
            result.raise_for_status()
            assert [row["id"] for row in result.json()["items"]] == [order["id"]]
            other = identities[1 - index][1]
            denied = await client.get(
                "/api/collections/orders/records/" + other["id"], headers=headers
            )
            assert denied.status_code == 404
            denied = await client.post(
                "/api/collections/orders/records",
                headers=headers,
                json={
                    "order_id": "forged",
                    "site_id": "site_b",
                    "status": "pending",
                    "total": 1,
                    "currency": "USD",
                },
            )
            assert denied.status_code in (400, 403)

        # Site/property reads retain caller credentials; fixture rules permit
        # these reads so the application's tenant checks can be exercised.
        for name in ("sites", "tenants", "properties"):
            response = await client.patch(
                "/api/collections/" + name,
                json={
                    "listRule": '@request.auth.id != ""',
                    "viewRule": '@request.auth.id != ""',
                },
            )
            response.raise_for_status()
        for name in ("order_items", "payments", "bookings", "availability"):
            schema = (await client.get("/api/collections/" + name)).json()
            response = await client.patch(
                "/api/collections/" + name, json=candidate(schema)
            )
            response.raise_for_status()
        await post(
            "/api/collections/properties/records",
            {
                "property_id": "service_a",
                "site_id": "site_a",
                "type": "spa_service",
                "status": "published",
            },
        )
        app = FastAPI()
        app.include_router(router)
        caller = PocketBaseClient(base, max_retries=1)
        server = PocketBaseClient(base, static_token=admin, max_retries=1)
        app.dependency_overrides[get_pocketbase_client] = lambda: caller
        app.dependency_overrides[get_static_pocketbase_client] = lambda: server
        settings = get_settings().model_copy(
            update={"pocketbase_auth_collection": "users"}
        )
        app.dependency_overrides[get_settings] = lambda: settings
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + identities[0][0]},
        ) as api:
            response = await api.post(
                "/sites/site_a/orders",
                json={
                    "items": [
                        {"property_id": "service_a", "quantity": 1, "unit_price": 0}
                    ]
                },
            )
            assert response.status_code == 201, response.text
            order_id = response.json()["order_id"]
            response = await api.post(
                f"/orders/{order_id}/fake-payment",
                json={"idempotency_key": "real_user_demo"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["amount"] == 0
            response = await api.patch(
                f"/orders/{order_id}", json={"status": "fulfilled"}
            )
            assert response.status_code == 200, response.text
            denied = await api.get(
                f"/orders/{order_id}",
                headers={"Authorization": "Bearer " + identities[1][0]},
            )
            assert denied.status_code == 404
            response = await api.post(
                "/sites/site_a/bookings",
                json={
                    "property_id": "service_a",
                    "customer_name": "Demo",
                    "customer_email": "demo@example.com",
                    "date": "2026-10-19",
                    "start_time": "10:00",
                    "end_time": "11:00",
                },
            )
            assert response.status_code == 201, response.text
            booking_id = response.json()["booking_id"]
            for status in ("confirmed", "completed"):
                response = await api.patch(
                    f"/bookings/{booking_id}", json={"status": status}
                )
                assert response.status_code == 200, response.text
