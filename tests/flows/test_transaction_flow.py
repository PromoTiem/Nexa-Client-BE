"""Full HTTP/service/persistence flows against a fresh disposable PocketBase.

NEXA_TEST_POCKETBASE_BINARY=/path/to/pocketbase pytest tests/flows -o addopts=''
Identity injection is explicit; these tests do not certify production PB rules.
"""

import asyncio
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.auth_models import AuthContext
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.routes.transactional import router
from app.interface.transaction_dependencies import get_transaction_client
from scripts.migrate_transactional import COLLECTIONS, schema_for


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    binary = os.environ.get("NEXA_TEST_POCKETBASE_BINARY")
    if not binary:
        pytest.skip(
            "Set NEXA_TEST_POCKETBASE_BINARY to run disposable persistence flows"
        )
    binary = str(Path(binary).resolve())
    root = tmp_path_factory.mktemp("transaction-flow")
    for directory in ("hooks", "migrations"):
        (root / directory).mkdir()
    password = "Flow-" + secrets.token_urlsafe(32)
    flags = [
        "--dir",
        str(root / "data"),
        "--hooksDir",
        str(root / "hooks"),
        "--migrationsDir",
        str(root / "migrations"),
    ]
    log = (root / "pocketbase.log").open("w")
    process = None
    try:
        subprocess.run(
            [binary, "superuser", "upsert", "flow@example.test", password, *flags],
            check=True,
            stdout=log,
            stderr=log,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        process = subprocess.Popen(
            [binary, "serve", f"--http=127.0.0.1:{port}", *flags],
            stdout=log,
            stderr=log,
        )
        with httpx.Client(base_url=base, trust_env=False, timeout=5) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Disposable PocketBase exited")
                try:
                    client.get("/api/health").raise_for_status()
                    break
                except httpx.HTTPError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("PocketBase readiness timeout")
            auth = client.post(
                "/api/collections/_superusers/auth-with-password",
                json={
                    "identity": "flow@example.test",
                    "password": password,
                },
            )
            auth.raise_for_status()
            token = auth.json()["token"]
            client.headers["Authorization"] = token
            schemas = {
                "tenants": [("tenant_id", "text", True)],
                "sites": [
                    ("site_id", "text", True),
                    ("tenant_id", "text", True),
                    ("config", "json", False),
                ],
                "properties": [
                    ("property_id", "text", True),
                    ("site_id", "text", True),
                    ("type", "text", True),
                    ("status", "text", True),
                    ("name", "text", False),
                    ("deleted_at", "date", False),
                ],
                **{
                    name: definition["fields"]
                    for name, definition in COLLECTIONS.items()
                },
            }
            for name, fields in schemas.items():
                # Candidate fixture corrections: valid zero/false, plus audit fields.
                fields = [
                    (field, kind, required and kind not in {"bool", "number"})
                    for field, kind, required in fields
                ]
                fields += [("created_at", "date", False), ("updated_at", "date", False)]
                response = client.post(
                    "/api/collections",
                    json={"name": name, "type": "base", "fields": schema_for(fields)},
                )
                response.raise_for_status()
            yield base, token, root
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log.close()


@pytest.fixture
async def flow(database):
    base, token, _ = database
    pb = PocketBaseClient(base, static_token=token, max_retries=1)
    suffix = secrets.token_hex(5)
    tenant_public = "tenant_" + suffix
    tenant = await pb.create_record("tenants", {"tenant_id": tenant_public})
    site_id = "site_" + suffix
    site = await pb.create_record(
        "sites", {"site_id": site_id, "tenant_id": tenant["id"], "config": {}}
    )
    property_id = "service_" + suffix
    prop = await pb.create_record(
        "properties",
        {
            "property_id": property_id,
            "site_id": site_id,
            "type": "spa_service",
            "status": "published",
            "name": "Demo massage",
        },
    )
    ctx = TenantContext(
        auth=AuthContext(
            token=token,
            record={"id": "fixture_user", "role": "owner", "tenant_id": tenant_public},
        ),
        tenant_id=tenant_public,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: ctx
    app.dependency_overrides[get_pocketbase_client] = lambda: pb
    app.dependency_overrides[get_transaction_client] = lambda: pb
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://flow",
    ) as client:
        yield client, pb, ctx, site, prop


async def make_order(client, site, prop, **extra):
    response = await client.post(
        f"/sites/{site['site_id']}/orders",
        json={
            "currency": "USD",
            "items": [
                {"property_id": prop["property_id"], "quantity": 3, "unit_price": 0.1}
            ],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def booking_body(prop, **extra):
    return {
        "property_id": prop["property_id"],
        "customer_name": "Demo guest",
        "customer_email": "demo@example.com",
        "date": "2026-10-19",
        "start_time": "10:00",
        "end_time": "11:00",
        **extra,
    }


async def test_order_fake_payment_fulfillment_and_retry(flow):
    client, _pb, _, site, prop = flow
    order = await make_order(client, site, prop)
    assert order["total"] == 0.3
    oid = order["order_id"]
    added = await client.post(
        f"/orders/{oid}/items",
        json={"property_id": prop["property_id"], "quantity": 2, "unit_price": 0.2},
    )
    assert added.status_code == 201, added.text
    assert (await client.get(f"/orders/{oid}")).json()["total"] == 0.7
    removed = await client.delete(f"/order_items/{added.json()['item_id']}")
    assert removed.status_code == 204, removed.text
    assert (await client.get(f"/orders/{oid}")).json()["total"] == 0.3
    assert (
        await client.delete(f"/order_items/{order['items'][0]['item_id']}")
    ).status_code == 409
    paid = await client.post(
        f"/orders/{oid}/fake-payment", json={"idempotency_key": "checkout_demo_001"}
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["metadata"]["simulated"] is True
    assert paid.json()["amount"] == 0.3
    retry = await client.post(
        f"/orders/{oid}/fake-payment", json={"idempotency_key": "checkout_demo_001"}
    )
    assert retry.json()["payment_id"] == paid.json()["payment_id"]
    assert len((await client.get(f"/orders/{oid}/payments")).json()) == 1
    assert (await client.get(f"/orders/{oid}")).json()["status"] == "paid"
    fulfilled = await client.patch(f"/orders/{oid}", json={"status": "fulfilled"})
    assert fulfilled.status_code == 200, fulfilled.text
    assert (
        await client.patch(f"/orders/{oid}", json={"status": "pending"})
    ).status_code == 409


async def test_payment_repair_after_partial_order_update(flow, monkeypatch):
    client, pb, _, site, prop = flow
    order = await make_order(client, site, prop)
    original = pb.update_record
    failed = False

    async def fail_once(collection, record_id, data, **kwargs):
        nonlocal failed
        if collection == "orders" and data.get("status") == "paid" and not failed:
            failed = True
            raise HTTPException(503, "Injected write failure")
        return await original(collection, record_id, data, **kwargs)

    monkeypatch.setattr(pb, "update_record", fail_once)
    path = f"/orders/{order['order_id']}/fake-payment"
    assert (
        await client.post(path, json={"idempotency_key": "repair_demo_001"})
    ).status_code == 503
    assert (
        await client.post(
            f"/orders/{order['order_id']}/items",
            json={"property_id": prop["property_id"], "quantity": 1, "unit_price": 10},
        )
    ).status_code == 409
    repaired = await client.post(path, json={"idempotency_key": "repair_demo_001"})
    assert repaired.status_code == 200, repaired.text
    assert len((await client.get(f"/orders/{order['order_id']}/payments")).json()) == 1
    assert (await client.get(f"/orders/{order['order_id']}")).json()["status"] == "paid"


async def test_concurrent_fake_payment_and_cancellation(flow):
    client, _, _, site, prop = flow
    order = await make_order(client, site, prop)
    oid = order["order_id"]
    responses = await asyncio.gather(
        *[
            client.post(
                f"/orders/{oid}/fake-payment",
                json={"idempotency_key": "concurrent_demo"},
            )
            for _ in range(4)
        ]
    )
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["payment_id"] for response in responses}) == 1
    cancelled = await client.patch(f"/orders/{oid}", json={"status": "cancelled"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["payments"][0]["status"] == "cancelled"
    replay = await client.post(
        f"/orders/{oid}/fake-payment", json={"idempotency_key": "concurrent_demo"}
    )
    assert replay.json()["status"] == "cancelled"


async def test_booking_lifecycle_availability_capacity_and_cancel(flow):
    client, _, _, site, prop = flow
    root = f"/sites/{site['site_id']}"
    slot = await client.post(
        root + "/availability",
        json={
            "property_id": prop["property_id"],
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "max_bookings": 1,
        },
    )
    assert slot.status_code == 201, slot.text
    responses = await asyncio.gather(
        *[client.post(root + "/bookings", json=booking_body(prop)) for _ in range(2)]
    )
    assert sorted(response.status_code for response in responses) == [201, 409], [
        r.text for r in responses
    ]
    booking = next(r.json() for r in responses if r.status_code == 201)
    path = f"/bookings/{booking['booking_id']}"
    assert (await client.patch(path, json={"status": "completed"})).status_code == 409
    assert (await client.patch(path, json={"status": "confirmed"})).status_code == 200
    assert (await client.delete(path)).status_code == 409
    assert (await client.patch(path, json={"status": "cancelled"})).status_code == 200
    replacement = await client.post(root + "/bookings", json=booking_body(prop))
    assert replacement.status_code == 201, replacement.text
    path = f"/bookings/{replacement.json()['booking_id']}"
    assert (await client.patch(path, json={"status": "confirmed"})).status_code == 200
    completed = await client.patch(path, json={"status": "completed"})
    assert completed.status_code == 200, completed.text
    assert (await client.patch(path, json={"start_time": "12:00"})).status_code == 409


async def test_booking_validation_publication_and_inactive_hours(flow):
    client, pb, _, site, prop = flow
    root = f"/sites/{site['site_id']}"
    for changes in (
        {"date": "2026-02-30"},
        {"end_time": "09:00"},
        {"start_time": "25:00"},
        {"customer_email": "bad"},
    ):
        assert (
            await client.post(root + "/bookings", json=booking_body(prop, **changes))
        ).status_code == 422
    await pb.update_record("properties", prop["id"], {"status": "draft"})
    assert (
        await client.post(root + "/bookings", json=booking_body(prop))
    ).status_code == 422
    await pb.update_record("properties", prop["id"], {"status": "published"})
    slot = await client.post(
        root + "/availability",
        json={
            "property_id": prop["property_id"],
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
            "is_active": False,
        },
    )
    assert slot.status_code == 201, slot.text
    assert (
        await client.post(root + "/bookings", json=booking_body(prop))
    ).status_code == 409


async def test_api_role_tenant_and_retained_site_boundaries(flow):
    client, pb, ctx, site, prop = flow
    order = await make_order(client, site, prop)
    ctx.auth.record["role"] = "member"
    assert (await client.get(f"/orders/{order['order_id']}")).status_code == 200
    assert (
        await client.post(
            f"/orders/{order['order_id']}/fake-payment",
            json={"idempotency_key": "member_demo_key"},
        )
    ).status_code == 403
    ctx.auth.record["role"] = "guest"
    assert (await client.get(f"/orders/{order['order_id']}")).status_code == 403
    ctx.auth.record["role"] = "owner"
    ctx.auth.record["tenant_id"] = "another_tenant"
    assert (await client.get(f"/orders/{order['order_id']}")).status_code == 404
    ctx.auth.record["tenant_id"] = ctx.tenant_id
    await pb.update_record(
        "sites", site["id"], {"config": {"_nexa_lifecycle": {"deleted_at": "now"}}}
    )
    assert (
        await client.post(f"/sites/{site['site_id']}/bookings", json=booking_body(prop))
    ).status_code == 404


async def test_failed_order_creation_stays_hidden(flow, monkeypatch):
    client, pb, _, site, prop = flow
    original = pb.create_record

    async def fail_item(collection, data, **kwargs):
        if collection == "order_items":
            raise HTTPException(503, "Injected item failure")
        return await original(collection, data, **kwargs)

    monkeypatch.setattr(pb, "create_record", fail_item)
    response = await client.post(
        f"/sites/{site['site_id']}/orders",
        json={
            "items": [
                {"property_id": prop["property_id"], "quantity": 1, "unit_price": 10}
            ]
        },
    )
    assert response.status_code == 503, response.text
    listed = await client.get(f"/sites/{site['site_id']}/orders")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []
