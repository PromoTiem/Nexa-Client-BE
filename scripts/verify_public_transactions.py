"""Create a labelled synthetic FE test tenant and verify public transaction flows.

Credentials and record inventory are stored only in the private rollback directory.
Synthetic records remain available for FE testing; no customer records are changed.
"""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

import httpx


async def main():
    from app.config import get_settings

    os.umask(0o077)
    target = Path(sys.argv[1])
    settings = get_settings()
    suffix = secrets.token_hex(5)
    password = "FeTest-" + secrets.token_urlsafe(24)
    email = f"nexa-fe-test-{suffix}@example.com"
    inventory = {"email": email, "password": password, "records": {}}
    async with httpx.AsyncClient(base_url=settings.pocketbase_url, timeout=30) as pb:
        response = await pb.post(
            "/api/collections/_superusers/auth-with-password",
            json={
                "identity": settings.pocketbase_admin_email,
                "password": settings.pocketbase_admin_password,
            },
        )
        response.raise_for_status()
        pb.headers["Authorization"] = response.json()["token"]

        async def create(collection, data):
            response = await pb.post(
                f"/api/collections/{collection}/records", json=data
            )
            if not response.is_success:
                raise RuntimeError(
                    f"Fixture creation failed: {collection}, HTTP {response.status_code}"
                )
            row = response.json()
            inventory["records"][collection] = row["id"]
            (target / "fe-test-fixture.json").write_text(
                json.dumps(inventory, indent=2)
            )
            return row

        tenant_id = "fe_test_" + suffix
        tenant = await create(
            "tenants",
            {
                "tenant_id": tenant_id,
                "name": "FE synthetic transaction acceptance",
                "status": "active",
            },
        )
        templates = await pb.get(
            "/api/collections/templates/records", params={"perPage": 1}
        )
        templates.raise_for_status()
        template = templates.json()["items"][0]["id"]
        site_id = "fe_test_" + suffix
        await create(
            "sites",
            {
                "site_id": site_id,
                "tenant_id": tenant["id"],
                "template_id": template,
                "config": {"name": "FE synthetic test - no deployment"},
                "status": "draft",
            },
        )
        property_id = "fe_service_" + suffix
        await create(
            "properties",
            {
                "property_id": property_id,
                "site_id": site_id,
                "name": "Synthetic test service",
                "type": "spa_service",
                "status": "published",
                "fields": [],
                "groups": [],
            },
        )
        await create(
            "users",
            {
                "email": email,
                "password": password,
                "passwordConfirm": password,
                "tenant_id": tenant_id,
                "role": "owner",
                "status": "active",
                "name": "FE test owner",
                "first_auth": False,
            },
        )
        inventory.update(site_id=site_id, property_id=property_id)
        (target / "fe-test-fixture.json").write_text(json.dumps(inventory, indent=2))
        auth = await pb.post(
            "/api/collections/users/auth-with-password",
            json={"identity": email, "password": password},
        )
        auth.raise_for_status()
        token = auth.json()["token"]
        checks = []
        async with httpx.AsyncClient(
            base_url="https://api-client.promotiem.shop",
            headers={"Authorization": "Bearer " + token},
            timeout=30,
        ) as api:

            async def request(method, path, data, expected):
                response = await api.request(method, path, json=data)
                if response.status_code != expected:
                    raise RuntimeError(
                        f"Public {method} {path}: expected {expected}, received {response.status_code}; {response.text[:300]}"
                    )
                checks.append(f"{method} {path}: {expected}")
                return response.json() if response.content else {}

            order = await request(
                "POST",
                f"/sites/{site_id}/orders",
                {
                    "currency": "USD",
                    "items": [
                        {"property_id": property_id, "quantity": 2, "unit_price": 1.25}
                    ],
                },
                201,
            )
            inventory["order_id"] = order["order_id"]
            path = f"/orders/{order['order_id']}"
            paid = await request(
                "POST",
                path + "/fake-payment",
                {"idempotency_key": "production_smoke_" + suffix},
                200,
            )
            replay = await request(
                "POST",
                path + "/fake-payment",
                {"idempotency_key": "production_smoke_" + suffix},
                200,
            )
            assert (
                paid["payment_id"] == replay["payment_id"]
                and paid["metadata"]["simulated"]
            )
            await request("PATCH", path, {"status": "fulfilled"}, 200)
            booking = await request(
                "POST",
                f"/sites/{site_id}/bookings",
                {
                    "property_id": property_id,
                    "customer_name": "Synthetic guest",
                    "customer_email": "guest@example.com",
                    "date": "2026-10-19",
                    "start_time": "10:00",
                    "end_time": "11:00",
                },
                201,
            )
            inventory["booking_id"] = booking["booking_id"]
            for state in ("confirmed", "completed"):
                await request(
                    "PATCH",
                    f"/bookings/{booking['booking_id']}",
                    {"status": state},
                    200,
                )
            await request(
                "POST",
                f"/sites/{site_id}/availability",
                {
                    "property_id": property_id,
                    "day_of_week": "monday",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "max_bookings": 0,
                    "is_active": False,
                },
                201,
            )
        direct = await pb.post(
            "/api/collections/orders/records",
            headers={"Authorization": token},
            json={
                "order_id": "direct_denied",
                "site_id": site_id,
                "status": "pending",
                "total": 1,
                "currency": "USD",
            },
        )
        assert direct.status_code in (400, 403)
        checks.append("Direct user PocketBase order write denied")
        (target / "fe-test-fixture.json").write_text(json.dumps(inventory, indent=2))
        (target / "public-verification.json").write_text(
            json.dumps({"checks": checks, "site_id": site_id}, indent=2)
        )
        print(
            "Public authenticated transaction verification passed:",
            len(checks),
            "checks",
        )
        print("Synthetic site:", site_id)
        print("Private fixture credentials:", target / "fe-test-fixture.json")


if __name__ == "__main__":
    asyncio.run(main())
