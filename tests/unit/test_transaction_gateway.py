from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.access import AuthContext
from app.application.services.transaction_gateway import TransactionGateway


def gateway(role="owner"):
    caller, server = AsyncMock(), AsyncMock()
    server.find_one_by_filter.return_value = {
        "site_id": "s",
        "tenant_id": "tr",
        "config": {},
    }
    server.find_record_by_id.return_value = {"tenant_id": "t"}
    return TransactionGateway(
        caller,
        server,
        AuthContext("user-token", {"id": "u", "role": role, "tenant_id": "t"}),
    ), server


async def test_write_uses_server_token_only_after_ownership_check():
    client, server = gateway()
    await client.create_record(
        "orders", {"site_id": "s"}, token="user-token", user_id="forged"
    )
    server.create_record.assert_awaited_once_with(
        "orders", {"site_id": "s"}, user_id="u"
    )


async def test_cross_tenant_write_denied():
    client, server = gateway()
    server.find_record_by_id.return_value = {"tenant_id": "other"}
    with pytest.raises(HTTPException) as error:
        await client.create_record("orders", {"site_id": "s"})
    assert error.value.status_code == 404
    server.create_record.assert_not_called()


async def test_member_cannot_write():
    client, server = gateway("member")
    with pytest.raises(HTTPException) as error:
        await client.create_record("orders", {"site_id": "s"})
    assert error.value.status_code == 403
    server.create_record.assert_not_called()


async def test_unscoped_list_rejected():
    client, server = gateway()
    with pytest.raises(HTTPException):
        await client.list_records("orders")
    server.list_records.assert_not_called()


async def test_retained_parent_rejected():
    client, server = gateway()
    server.find_one_by_filter.return_value = {
        "config": {"_nexa_lifecycle": {"deleted_at": "now"}}
    }
    with pytest.raises(HTTPException) as error:
        await client.create_record("orders", {"site_id": "s"})
    assert error.value.status_code == 404
    server.create_record.assert_not_called()
