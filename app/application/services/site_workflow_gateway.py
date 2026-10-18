"""Elevate only site bookkeeping writes; other resource calls retain user auth."""

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.application.services.account_service import enforce_account_access


class SiteWorkflowGateway:
    def __init__(self, caller, server, auth, purpose):
        if purpose not in {"serve", "bucket"}:
            raise ValueError("Unknown site workflow")
        self.caller, self.server, self.auth, self.purpose = (
            caller,
            server,
            auth,
            purpose,
        )

    def __getattr__(self, name):
        return getattr(self.caller, name)

    async def update_record(
        self, collection, record_id, data, token=None, user_id=None
    ):
        if collection != "sites":
            return await self.caller.update_record(
                collection, record_id, data, token=token, user_id=user_id
            )
        enforce_account_access(self.auth.record)
        if self.auth.record.get("role") not in {"owner", "admin", "member"}:
            raise HTTPException(403, "Site workflow permission required")
        allowed = (
            {"serve_status", "serve_stage_log", "status"}
            if self.purpose == "serve"
            else {"bucket_name"}
        )
        if not data or set(data) - allowed:
            raise HTTPException(422, "Unsupported site workflow fields")
        site = await self.server.find_record_by_id("sites", record_id)
        assert_site_active(site)
        tenant = await self.server.find_record_by_id("tenants", site["tenant_id"])
        if tenant.get("tenant_id") != self.auth.record["tenant_id"]:
            raise HTTPException(404, "Site not found")
        if self.purpose == "bucket":
            from app.application.services.bucket_resolver import sanitize_bucket_name

            if site.get("bucket_name") or data["bucket_name"] != sanitize_bucket_name(
                site["site_id"]
            ):
                raise HTTPException(409, "Bucket identity cannot be replaced")
        return await self.server.update_record(
            "sites", record_id, data, user_id=self.auth.record["id"]
        )
