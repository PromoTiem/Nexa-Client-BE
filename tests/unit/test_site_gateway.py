from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.access import AuthContext
from app.application.services.site_gateway import SiteGateway


def gateway(operation="update", role="member"):
    server = AsyncMock()

    async def lookup(collection, record_id):
        return (
            {"tenant_id": "tenant"}
            if collection == "tenants"
            else {"tenant_id": "internal", "config": {}}
        )

    server.find_record_by_id.side_effect = lookup
    return SiteGateway(
        AsyncMock(),
        server,
        AuthContext(
            "caller",
            {"id": "u", "tenant_id": "tenant", "role": role, "status": "active"},
        ),
        operation,
    ), server


async def test_owned_site_update_uses_server_credentials():
    client, server = gateway()
    await client.update_record(
        "sites", "site", {"config": {"name": "Demo"}}, token="caller"
    )
    server.update_record.assert_awaited_once_with(
        "sites", "site", {"config": {"name": "Demo"}}, user_id="u"
    )


@pytest.mark.parametrize(
    "patch",
    [{"tenant_id": "other"}, {"config": {"_nexa_lifecycle": {"deleted_at": "now"}}}],
)
async def test_protected_site_fields_rejected(patch):
    client, server = gateway()
    with pytest.raises(HTTPException):
        await client.update_record("sites", "site", patch)
    server.update_record.assert_not_called()


async def test_hard_delete_only_rolls_back_this_request_creation():
    client, server = gateway("create")
    server.create_record.return_value = {"id": "new"}
    await client.create_record("sites", {"tenant_id": "internal"})
    await client.delete_record("sites", "new")
    with pytest.raises(HTTPException):
        await client.delete_record("sites", "old")
    server.delete_record.assert_awaited_once_with("sites", "new")


async def test_member_cannot_retain_site():
    client, server = gateway("delete")
    with pytest.raises(HTTPException):
        await client.update_record("sites", "site", {"default": False})
    server.update_record.assert_not_called()
