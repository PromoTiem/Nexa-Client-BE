"""Scoped site-management writes; reads retain caller-token semantics."""

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.application.services.account_service import enforce_account_access


class SiteGateway:
    def __init__(self, caller, server, auth, operation):
        self.caller, self.server, self.auth, self.operation = (
            caller,
            server,
            auth,
            operation,
        )
        self.created = set()

    def __getattr__(self, name):
        return getattr(self.caller, name)

    def _permit(self, collection):
        enforce_account_access(self.auth.record)
        roles = (
            {"owner", "admin"}
            if self.operation == "delete"
            else {"owner", "admin", "member"}
        )
        if collection != "sites" or self.auth.record.get("role") not in roles:
            raise HTTPException(403, "Site management permission required")

    async def _tenant(self, tenant_id):
        tenant = await self.server.find_record_by_id("tenants", tenant_id)
        if tenant.get("tenant_id") != self.auth.record["tenant_id"]:
            raise HTTPException(404, "Site not found")

    async def create_record(self, collection, data, token=None, user_id=None):
        self._permit(collection)
        if self.operation != "create":
            raise HTTPException(403, "Site creation not allowed")
        await self._tenant(data.get("tenant_id"))
        if "_nexa_lifecycle" in (data.get("config") or {}):
            raise HTTPException(422, "Lifecycle is server owned")
        record = await self.server.create_record(
            collection, data, user_id=self.auth.record["id"]
        )
        self.created.add(record["id"])
        return record

    async def update_record(
        self, collection, record_id, data, token=None, user_id=None
    ):
        self._permit(collection)
        record = await self.server.find_record_by_id(collection, record_id)
        await self._tenant(record["tenant_id"])
        assert_site_active(record)
        if set(data) - {
            "template_id",
            "domain",
            "domain_id",
            "config",
            "status",
            "default",
        }:
            raise HTTPException(422, "Protected site fields cannot be changed")
        if "config" in data and self.operation != "delete":
            if (data.get("config") or {}).get("_nexa_lifecycle") != (
                record.get("config") or {}
            ).get("_nexa_lifecycle"):
                raise HTTPException(422, "Lifecycle is server owned")
        return await self.server.update_record(
            collection, record_id, data, user_id=self.auth.record["id"]
        )

    async def delete_record(self, collection, record_id, token=None):
        self._permit(collection)
        if self.operation != "create" or record_id not in self.created:
            raise HTTPException(
                403, "Hard deletion only allowed for provisioning rollback"
            )
        await self.server.delete_record(collection, record_id)
        self.created.remove(record_id)
