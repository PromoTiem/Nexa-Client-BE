from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.access import AuthContext
from app.application.services.account_gateway import AccountGateway


def setup(role="owner"):
    server = AsyncMock()
    server.find_record_by_id.return_value = {
        "id": "member",
        "tenant_id": "t",
        "role": "member",
    }
    return AccountGateway(
        server,
        AuthContext(
            "caller",
            {"id": "actor", "tenant_id": "t", "role": role, "status": "active"},
        ),
    ), server


async def test_scoped_admin_write_uses_server_credential():
    gateway, server = setup()
    await gateway.update_record(
        "users", "member", {"status": "suspended"}, token="caller"
    )
    server.update_record.assert_awaited_once_with(
        "users", "member", {"status": "suspended"}, user_id="actor"
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"tenant_id": "foreign"},
        {"is_superuser": True},
        {"password": "new"},
        {"role": "owner"},
    ],
)
async def test_protected_mutations_rejected(patch):
    gateway, server = setup()
    with pytest.raises(HTTPException):
        await gateway.update_record("users", "member", patch)
    server.update_record.assert_not_called()


async def test_foreign_user_rejected():
    gateway, server = setup()
    server.find_record_by_id.return_value = {"tenant_id": "foreign", "role": "guest"}
    with pytest.raises(HTTPException) as error:
        await gateway.update_record("users", "foreign", {"name": "changed"})
    assert error.value.status_code == 404
    server.update_record.assert_not_called()


async def test_admin_cannot_modify_other_admin():
    gateway, server = setup("admin")
    server.find_record_by_id.return_value = {"tenant_id": "t", "role": "admin"}
    with pytest.raises(HTTPException) as error:
        await gateway.update_record("users", "peer", {"status": "inactive"})
    assert error.value.status_code == 403


async def test_member_cannot_administer_accounts():
    gateway, server = setup("member")
    with pytest.raises(HTTPException):
        await gateway.collection_list("users")
    server.collection_list.assert_not_called()
