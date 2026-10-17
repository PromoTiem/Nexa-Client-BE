"""Tenant-bound account administration; never forwards arbitrary admin writes."""

from fastapi import HTTPException

from app.application.services.account_service import enforce_account_access
from app.infrastructure.pocketbase.filters import sanitize_filter_value

RANK = {"owner": 0, "admin": 1, "member": 2, "guest": 3}


class AccountGateway:
    def __init__(self, server, auth):
        self.server, self.auth = server, auth

    def _permit(self, collection):
        enforce_account_access(self.auth.record)
        if collection != "users" or self.auth.record.get("role") not in {
            "owner",
            "admin",
        }:
            raise HTTPException(403, "Account administration permission required")

    def _owns(self, record):
        if record.get("tenant_id") != self.auth.record["tenant_id"]:
            raise HTTPException(404, "User not found")

    def _lower_role(self, role):
        if role not in RANK or RANK[self.auth.record["role"]] >= RANK[role]:
            raise HTTPException(403, "Cannot manage an equal or higher role")

    async def collection_list(self, collection, token=None, filter_expr=None, **kwargs):
        self._permit(collection)
        scope = f'tenant_id="{sanitize_filter_value(self.auth.record["tenant_id"])}"'
        query = scope + (f" && ({filter_expr})" if filter_expr else "")
        result = await self.server.collection_list(
            collection, filter_expr=query, **kwargs
        )
        for record in result.get("items", []):
            self._owns(record)
        return result

    async def find_record_by_id(self, collection, record_id, token=None):
        self._permit(collection)
        record = await self.server.find_record_by_id(collection, record_id)
        self._owns(record)
        return record

    async def create_record(self, collection, data, token=None):
        self._permit(collection)
        self._owns(data)
        self._lower_role(data.get("role"))
        allowed = {
            "email",
            "password",
            "passwordConfirm",
            "name",
            "phone",
            "tenant_id",
            "role",
            "status",
            "first_auth",
            "metadata",
        }
        if (
            set(data) - allowed
            or data.get("status") != "active"
            or data.get("first_auth") is not True
        ):
            raise HTTPException(422, "Invalid account creation fields")
        return await self.server.create_record(
            collection, data, user_id=self.auth.record["id"]
        )

    async def update_record(self, collection, record_id, data, token=None):
        record = await self.find_record_by_id(collection, record_id)
        self._lower_role(record.get("role"))
        if "role" in data:
            self._lower_role(data["role"])
        if set(data) - {"name", "phone", "role", "status", "metadata", "is_deleted"}:
            raise HTTPException(422, "Protected account fields cannot be changed")
        if "status" in data and data["status"] not in {
            "active",
            "inactive",
            "suspended",
            "pending",
        }:
            raise HTTPException(422, "Invalid account status")
        if "is_deleted" in data and (
            data["is_deleted"] is not True or data.get("status") != "inactive"
        ):
            raise HTTPException(422, "Invalid account deletion")
        return await self.server.update_record(
            collection, record_id, data, user_id=self.auth.record["id"]
        )
