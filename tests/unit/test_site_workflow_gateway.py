from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.access import AuthContext
from app.application.services.site_workflow_gateway import SiteWorkflowGateway


def setup(purpose="serve", role="member", tenant="tenant"):
    caller, server = AsyncMock(), AsyncMock()
    site = {"site_id": "demo-site", "tenant_id": "internal", "config": {}}

    async def lookup(collection, record_id):
        return site if collection == "sites" else {"tenant_id": tenant}

    server.find_record_by_id.side_effect = lookup
    auth = AuthContext(
        "user-token",
        {"id": "actor", "role": role, "tenant_id": "tenant", "status": "active"},
    )
    return SiteWorkflowGateway(caller, server, auth, purpose), caller, server, site


async def test_serve_bookkeeping_uses_scoped_server_identity():
    gateway, _, server, _ = setup()
    await gateway.update_record(
        "sites", "s", {"serve_status": "live", "status": "live"}, token="user-token"
    )
    server.update_record.assert_awaited_once_with(
        "sites", "s", {"serve_status": "live", "status": "live"}, user_id="actor"
    )


async def test_file_updates_keep_user_credential():
    gateway, caller, server, _ = setup("bucket")
    await gateway.update_record(
        "media", "file", {"status": "ready"}, token="user-token", user_id="actor"
    )
    caller.update_record.assert_awaited_once_with(
        "media", "file", {"status": "ready"}, token="user-token", user_id="actor"
    )
    server.update_record.assert_not_called()


@pytest.mark.parametrize(
    "purpose,data", [("serve", {"config": {}}), ("bucket", {"serve_status": "live"})]
)
async def test_workflow_field_boundaries(purpose, data):
    gateway, _, server, _ = setup(purpose)
    with pytest.raises(HTTPException) as error:
        await gateway.update_record("sites", "s", data)
    assert error.value.status_code == 422
    server.update_record.assert_not_called()


@pytest.mark.parametrize(
    "role,tenant,retained",
    [
        ("guest", "tenant", False),
        ("member", "other", False),
        ("member", "tenant", True),
    ],
)
async def test_denies_guest_foreign_and_retained(role, tenant, retained):
    gateway, _, server, site = setup(role=role, tenant=tenant)
    if retained:
        site["config"] = {"_nexa_lifecycle": {"deleted_at": "now"}}
    with pytest.raises(HTTPException):
        await gateway.update_record("sites", "s", {"serve_status": "live"})
    server.update_record.assert_not_called()


async def test_bucket_can_only_initialize_canonical_name():
    gateway, _, server, site = setup("bucket")
    await gateway.update_record("sites", "s", {"bucket_name": "demo-site"})
    assert server.update_record.await_count == 1
    site["bucket_name"] = "demo-site"
    with pytest.raises(HTTPException):
        await gateway.update_record("sites", "s", {"bucket_name": "other"})
