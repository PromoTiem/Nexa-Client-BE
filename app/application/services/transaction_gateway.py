"""Request-scoped transaction gateway: user identity, server persistence credential.

Never exposes the server token and never permits unscoped transaction records.
Direct PocketBase writes remain locked. Nontransaction methods retain caller auth.
"""

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.infrastructure.pocketbase.filters import sanitize_filter_value

TRANSACTIONS = {"orders", "order_items", "payments", "bookings", "availability"}


class TransactionGateway:
    def __init__(self, caller, server, auth):
        self.caller, self.server, self.auth = caller, server, auth

    def __getattr__(self, name):
        return getattr(self.caller, name)

    async def _scope(self, collection, record):
        if collection in {"order_items", "payments"}:
            order_id = sanitize_filter_value(record.get("order_id", ""))
            parent = await self.server.find_one_by_filter(
                "orders", f'order_id="{order_id}"'
            )
            # Hidden drafts are allowed while their item creation is in progress.
            site_id = parent.get("site_id")
        else:
            site_id = record.get("site_id")
        if not site_id:
            raise HTTPException(404, "Transaction not found")
        site = await self.server.find_one_by_filter(
            "sites", f'site_id="{sanitize_filter_value(site_id)}"'
        )
        assert_site_active(site)
        tenant = await self.server.find_record_by_id("tenants", site["tenant_id"])
        if (
            not self.auth.record.get("tenant_id")
            or tenant.get("tenant_id") != self.auth.record["tenant_id"]
        ):
            raise HTTPException(404, "Transaction not found")

    def _write_permission(self):
        if self.auth.record.get("role") not in {"owner", "admin"}:
            raise HTTPException(403, "Transaction management permission required")

    async def list_records(self, collection, token=None, **kwargs):
        if collection not in TRANSACTIONS:
            return await self.caller.list_records(collection, token=token, **kwargs)
        if not kwargs.get("filter"):
            raise HTTPException(403, "Scoped transaction query required")
        result = await self.server.list_records(collection, **kwargs)
        for record in result.get("items", []):
            await self._scope(collection, record)
        return result

    async def find_one_by_filter(self, collection, filter_expr, token=None, **kwargs):
        if collection not in TRANSACTIONS:
            return await self.caller.find_one_by_filter(
                collection, filter_expr, token=token, **kwargs
            )
        record = await self.server.find_one_by_filter(collection, filter_expr, **kwargs)
        await self._scope(collection, record)
        return record

    async def create_record(self, collection, data, token=None, user_id=None):
        if collection not in TRANSACTIONS:
            raise HTTPException(403, "Unsupported transaction write")
        self._write_permission()
        await self._scope(collection, data)
        return await self.server.create_record(
            collection, data, user_id=self.auth.record["id"]
        )

    async def update_record(
        self, collection, record_id, data, token=None, user_id=None
    ):
        if collection not in TRANSACTIONS:
            raise HTTPException(403, "Unsupported transaction write")
        self._write_permission()
        record = await self.server.find_record_by_id(collection, record_id)
        await self._scope(collection, record)
        for key in (
            "site_id",
            "order_id",
            "booking_id",
            "item_id",
            "payment_id",
            "availability_id",
        ):
            if key in data and data[key] != record.get(key):
                raise HTTPException(
                    422, "Transaction parent and identity are immutable"
                )
        return await self.server.update_record(
            collection, record_id, data, user_id=self.auth.record["id"]
        )

    async def delete_record(self, collection, record_id, token=None):
        if collection not in {"order_items", "availability"}:
            raise HTTPException(403, "Hard deletion is not supported")
        self._write_permission()
        record = await self.server.find_record_by_id(collection, record_id)
        await self._scope(collection, record)
        return await self.server.delete_record(collection, record_id)
