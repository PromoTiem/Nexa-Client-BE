from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.application.services import booking_policy
from app.application.services.order_policy import (
    finite_decimal,
    line_total,
    money,
    require_editable,
    serialize_order,
    validate_transition,
)
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value


def filter_value(value: str) -> str:
    return f'"{sanitize_filter_value(value)}"'


class TransactionalService:
    """Read-side access to property-linked orders and bookings."""

    async def _order_children(
        self, pb: PocketBaseClient, token: str, collection: str, order_id: str
    ) -> list[dict[str, Any]]:
        items = []
        page = 1
        while True:
            result = await pb.list_records(
                collection,
                token=token,
                filter=f"order_id={filter_value(order_id)}",
                sort="id",
                page=page,
                per_page=100,
            )
            batch = result.get("items", [])
            items.extend(batch)
            if page >= result.get("totalPages", 1):
                return items
            if not batch:
                raise HTTPException(502, "Incomplete order child pagination")
            page += 1

    async def list_orders(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        *,
        page: int = 1,
        per_page: int = 50,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        parts = [f"site_id={filter_value(site_id)}", 'deleted_at=""']
        if status:
            parts.append(f"status={filter_value(status)}")
        if date_from:
            parts.append(f"created_at>={filter_value(date_from)}")
        if date_to:
            parts.append(f"created_at<={filter_value(date_to)}")
        return await pb.list_records(
            "orders",
            token=token,
            filter=" && ".join(parts),
            sort="-created_at",
            page=page,
            per_page=per_page,
        )

    async def get_order(
        self,
        pb: PocketBaseClient,
        token: str,
        order_id: str,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        parts = [f"order_id={filter_value(order_id)}", 'deleted_at=""']
        if site_id:
            parts.append(f"site_id={filter_value(site_id)}")
        order = await pb.find_one_by_filter("orders", " && ".join(parts), token=token)
        item_records = await self._order_children(pb, token, "order_items", order_id)
        payment_records = await self._order_children(pb, token, "payments", order_id)
        property_map = await self._properties(
            pb,
            token,
            order["site_id"],
            [item.get("property_id", "") for item in item_records],
        )
        items = [
            {
                "item_id": item["item_id"],
                "order_id": item["order_id"],
                "property_id": item["property_id"],
                "quantity": item.get("quantity", 0),
                "unit_price": item.get("unit_price", 0),
                "total_price": item.get("total_price", 0),
                "variation": item.get("variation"),
                "metadata": item.get("metadata"),
                "property": property_map.get(item.get("property_id")),
            }
            for item in item_records
        ]
        return {
            "order_id": order["order_id"],
            "site_id": order["site_id"],
            "customer_name": order.get("customer_name"),
            "customer_email": order.get("customer_email"),
            "customer_phone": order.get("customer_phone"),
            "status": order.get("status", "pending"),
            "total": order.get("total", 0),
            "currency": order.get("currency", "USD"),
            "item_count": len(items),
            "created_at": order.get("created_at"),
            "updated_at": order.get("updated_at"),
            "notes": order.get("notes"),
            "metadata": order.get("metadata"),
            "items": items,
            "payments": payment_records,
        }

    async def create_order(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        data = dict(data)
        items = data.pop("items")
        if not items:
            raise HTTPException(422, "An order requires at least one item")
        for item in items:
            finite_decimal(item["quantity"], positive=True)
            finite_decimal(item["unit_price"])
        properties = await self._properties(
            pb, token, site_id, [item["property_id"] for item in items]
        )
        if len(properties) != len({item["property_id"] for item in items}):
            raise HTTPException(
                status_code=422, detail="All order properties must belong to the site"
            )
        order_id = f"order_{uuid4().hex}"
        total = money(sum((line_total(item) for item in items), Decimal(0)))
        # Keep an incomplete order hidden until every requested item is persisted.
        draft_at = datetime.now(UTC).isoformat()
        order = await pb.create_record(
            "orders",
            {
                **data,
                "order_id": order_id,
                "site_id": site_id,
                "status": "pending",
                "total": total,
                "deleted_at": draft_at,
            },
            token=token,
            user_id=user_id,
        )
        for item in items:
            await pb.create_record(
                "order_items",
                {
                    "item_id": f"item_{uuid4().hex}",
                    "order_id": order_id,
                    "property_id": item["property_id"],
                    "quantity": item["quantity"],
                    "unit_price": item["unit_price"],
                    "total_price": money(line_total(item)),
                    "variation": item.get("variation"),
                    "metadata": item.get("metadata"),
                },
                token=token,
                user_id=user_id,
            )
        await pb.update_record(
            "orders", order["id"], {"deleted_at": ""}, token=token, user_id=user_id
        )
        return await self.get_order(pb, token, order_id, site_id)

    @serialize_order
    async def update_order(
        self,
        pb: PocketBaseClient,
        token: str,
        order_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        scope = f" && site_id={filter_value(site_id)}" if site_id else ""
        order = await pb.find_one_by_filter(
            "orders",
            f'order_id={filter_value(order_id)} && deleted_at=""{scope}',
            token=token,
        )
        if "status" in data:
            validate_transition(order.get("status"), data["status"])
            if data["status"] == "paid" and order["status"] != "paid":
                raise HTTPException(409, "Record payment before marking an order paid")
            if data["status"] == "cancelled" and order["status"] == "paid":
                payments = await self._order_children(pb, token, "payments", order_id)
                if any(
                    payment.get("method") != "fake"
                    and payment.get("status") == "completed"
                    for payment in payments
                ):
                    raise HTTPException(
                        409, "Resolve real payment refunds before cancellation"
                    )
                for payment in payments:
                    if (
                        payment.get("method") == "fake"
                        and payment.get("status") == "completed"
                    ):
                        await pb.update_record(
                            "payments",
                            payment["id"],
                            {"status": "cancelled"},
                            token=token,
                            user_id=user_id,
                        )
        allowed = {
            "status",
            "customer_name",
            "customer_email",
            "customer_phone",
            "notes",
            "metadata",
        }
        await pb.update_record(
            "orders",
            order["id"],
            {key: value for key, value in data.items() if key in allowed},
            token=token,
            user_id=user_id,
        )
        return await self.get_order(pb, token, order_id, order["site_id"])

    @serialize_order
    async def delete_order(
        self,
        pb: PocketBaseClient,
        token: str,
        order_id: str,
        user_id: str | None = None,
    ) -> None:
        order = await pb.find_one_by_filter(
            "orders", f'order_id={filter_value(order_id)} && deleted_at=""', token=token
        )
        if order.get("status") not in {"pending", "cancelled"}:
            raise HTTPException(409, "Paid or fulfilled orders cannot be deleted")
        await self._require_unpaid(pb, token, order_id)
        await pb.update_record(
            "orders",
            order["id"],
            {"deleted_at": datetime.now(UTC).isoformat()},
            token=token,
            user_id=user_id,
        )

    @serialize_order
    async def add_order_item(
        self,
        pb: PocketBaseClient,
        token: str,
        order_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        order = await pb.find_one_by_filter(
            "orders", f'order_id={filter_value(order_id)} && deleted_at=""', token=token
        )
        require_editable(order)
        await self._require_unpaid(pb, token, order_id)
        finite_decimal(data["quantity"], positive=True)
        finite_decimal(data["unit_price"])
        properties = await self._properties(
            pb, token, order["site_id"], [data["property_id"]]
        )
        if data["property_id"] not in properties:
            raise HTTPException(
                status_code=422, detail="Order property must belong to the order site"
            )
        item = await pb.create_record(
            "order_items",
            {
                "item_id": f"item_{uuid4().hex}",
                "order_id": order_id,
                **data,
                "total_price": money(line_total(data)),
            },
            token=token,
            user_id=user_id,
        )
        await self._refresh_order_total(pb, token, order, user_id)
        return item

    async def _refresh_order_total(self, pb, token, order, user_id=None):
        items = await self._order_children(pb, token, "order_items", order["order_id"])
        total = money(sum((line_total(item) for item in items), Decimal(0)))
        await pb.update_record(
            "orders", order["id"], {"total": total}, token=token, user_id=user_id
        )
        return total

    async def _require_unpaid(self, pb, token, order_id):
        payments = await self._order_children(pb, token, "payments", order_id)
        if any(
            payment.get("status") not in {"failed", "cancelled"} for payment in payments
        ):
            raise HTTPException(
                409, "Resolve the existing payment before editing order items"
            )

    async def delete_order_item(
        self, pb: PocketBaseClient, token: str, item_id: str, user_id: str | None = None
    ) -> None:
        item = await pb.find_one_by_filter(
            "order_items", f"item_id={filter_value(item_id)}", token=token
        )
        await self._delete_order_item(pb, token, item["order_id"], item, user_id)

    @serialize_order
    async def _delete_order_item(self, pb, token, order_id, item, user_id=None):
        order = await pb.find_one_by_filter(
            "orders", f'order_id={filter_value(order_id)} && deleted_at=""', token=token
        )
        require_editable(order)
        await self._require_unpaid(pb, token, order_id)
        items = await self._order_children(pb, token, "order_items", order_id)
        if len(items) <= 1:
            raise HTTPException(409, "An order must retain at least one item")
        await pb.delete_record("order_items", item["id"], token=token)
        await self._refresh_order_total(pb, token, order, user_id)

    async def list_payments(
        self, pb: PocketBaseClient, token: str, order_id: str
    ) -> list[dict[str, Any]]:
        await pb.find_one_by_filter(
            "orders", f'order_id={filter_value(order_id)} && deleted_at=""', token=token
        )
        return await self._order_children(pb, token, "payments", order_id)

    @serialize_order
    async def add_payment(
        self,
        pb: PocketBaseClient,
        token: str,
        order_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        order = await pb.find_one_by_filter(
            "orders", f'order_id={filter_value(order_id)} && deleted_at=""', token=token
        )
        if order.get("status") not in {"pending", "paid"}:
            raise HTTPException(409, "Order does not accept payments")
        finite_decimal(data["amount"], positive=True)
        if data.get("currency", "USD") != order.get("currency"):
            raise HTTPException(422, "Payment currency must match the order")
        if data.get("method") == "fake" or (
            data.get("transaction_ref") or ""
        ).startswith("fake:"):
            raise HTTPException(
                422, "Use the fake-payment endpoint for simulated checkout"
            )
        return await pb.create_record(
            "payments",
            {
                "payment_id": f"payment_{uuid4().hex}",
                "order_id": order["order_id"],
                **data,
            },
            token=token,
            user_id=user_id,
        )

    @serialize_order
    async def fake_payment(self, pb, token, order_id, idempotency_key, user_id=None):
        """Record a simulated full payment; no gateway or real charge is invoked."""
        order = await pb.find_one_by_filter(
            "orders", f'order_id={filter_value(order_id)} && deleted_at=""', token=token
        )
        payments = await self._order_children(pb, token, "payments", order_id)
        reference = "fake:" + idempotency_key
        existing = next(
            (
                payment
                for payment in payments
                if payment.get("transaction_ref") == reference
            ),
            None,
        )
        if existing is not None:
            if existing.get("method") != "fake" or existing.get("status") not in {
                "completed",
                "cancelled",
            }:
                raise HTTPException(
                    409, "Idempotency key belongs to a different payment"
                )
            if order["status"] == "pending" and existing["status"] == "completed":
                await pb.update_record(
                    "orders",
                    order["id"],
                    {"status": "paid"},
                    token=token,
                    user_id=user_id,
                )
            return existing
        require_editable(order)
        if any(
            payment.get("status") not in {"failed", "cancelled"} for payment in payments
        ):
            raise HTTPException(
                409, "Order already has a payment; resolve it before fake checkout"
            )
        items = await self._order_children(pb, token, "order_items", order_id)
        if not items:
            raise HTTPException(409, "Cannot pay an empty order")
        total = await self._refresh_order_total(pb, token, order, user_id)
        payment = await pb.create_record(
            "payments",
            {
                "payment_id": f"payment_{uuid4().hex}",
                "order_id": order_id,
                "method": "fake",
                "amount": total,
                "currency": order["currency"],
                "status": "completed",
                "transaction_ref": reference,
                "metadata": {"simulated": True, "provider": "nexa-demo"},
                "notes": "Simulated payment only; no money was charged.",
            },
            token=token,
            user_id=user_id,
        )
        # A retry with the same key repairs this update if it fails after creation.
        await pb.update_record(
            "orders", order["id"], {"status": "paid"}, token=token, user_id=user_id
        )
        return payment

    async def list_bookings(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        *,
        page: int = 1,
        per_page: int = 50,
        status: str | None = None,
        date: str | None = None,
        property_id: str | None = None,
    ) -> dict[str, Any]:
        parts = [f"site_id={filter_value(site_id)}", 'deleted_at=""']
        if status:
            parts.append(f"status={filter_value(status)}")
        if date:
            parts.append(f"date={filter_value(date)}")
        if property_id:
            parts.append(f"property_id={filter_value(property_id)}")
        return await pb.list_records(
            "bookings",
            token=token,
            filter=" && ".join(parts),
            sort="-date,-start_time",
            page=page,
            per_page=per_page,
        )

    async def get_booking(
        self,
        pb: PocketBaseClient,
        token: str,
        booking_id: str,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        parts = [f"booking_id={filter_value(booking_id)}", 'deleted_at=""']
        if site_id:
            parts.append(f"site_id={filter_value(site_id)}")
        booking = await pb.find_one_by_filter(
            "bookings", " && ".join(parts), token=token
        )
        property_map = await self._properties(
            pb, token, booking["site_id"], [booking["property_id"]]
        )
        prop = property_map.get(booking["property_id"])
        return {
            "booking_id": booking["booking_id"],
            "site_id": booking["site_id"],
            "property_id": booking["property_id"],
            "property_name": prop.get("name") if prop else None,
            "customer_name": booking.get("customer_name", ""),
            "customer_email": booking.get("customer_email", ""),
            "customer_phone": booking.get("customer_phone"),
            "date": booking.get("date", ""),
            "start_time": booking.get("start_time", ""),
            "end_time": booking.get("end_time", ""),
            "status": booking.get("status", "pending"),
            "created_at": booking.get("created_at"),
            "updated_at": booking.get("updated_at"),
            "notes": booking.get("notes"),
            "metadata": booking.get("metadata"),
            "fields": booking.get("fields", []),
            "property": prop,
            "legacy_property_id": (booking.get("metadata") or {}).get(
                "legacy_property_id"
            ),
        }

    async def _booking_slot(self, pb, token, site_id, data, booking_id=None):
        day = booking_policy.booking_date(data.get("date"))
        start, end = booking_policy.interval(data)
        prop = await self._properties(pb, token, site_id, [data["property_id"]])
        selected = prop.get(data["property_id"], {})
        if (
            selected.get("type") != "spa_service"
            or selected.get("status") != "published"
        ):
            raise HTTPException(
                422, "Booking requires a published spa_service on the site"
            )
        slots = await self._all_records(
            pb,
            token,
            "availability",
            f"site_id={filter_value(site_id)} && property_id={filter_value(data['property_id'])}",
        )
        if not slots:
            return  # Manual scheduling remains available until weekly hours are configured.
        candidates = [
            slot
            for slot in slots
            if slot.get("is_active")
            and slot.get("day_of_week") == booking_policy.DAYS[day.weekday()]
            and booking_policy.minutes(slot["start_time"]) <= start
            and booking_policy.minutes(slot["end_time"]) >= end
        ]
        if not candidates:
            raise HTTPException(409, "Requested booking is outside active availability")
        existing = await self._all_records(
            pb,
            token,
            "bookings",
            f'site_id={filter_value(site_id)} && property_id={filter_value(data["property_id"])} && deleted_at="" && (status="pending" || status="confirmed")',
        )
        events = []
        for other in existing:
            if (
                other.get("booking_id") == booking_id
                or booking_policy.booking_date(other["date"]) != day
            ):
                continue
            other_start, other_end = booking_policy.interval(other)
            if other_start < end and other_end > start:
                events.extend([(max(start, other_start), 1), (min(end, other_end), -1)])
        concurrent = peak = 0
        for _, delta in sorted(events):
            concurrent += delta
            peak = max(peak, concurrent)
        if not any(
            slot.get("max_bookings", 0) == 0 or peak < slot["max_bookings"]
            for slot in candidates
        ):
            raise HTTPException(409, "Requested booking slot is full")

    async def _all_records(self, pb, token, collection, filter_expr):
        records = []
        page = 1
        while True:
            result = await pb.list_records(
                collection,
                token=token,
                filter=filter_expr,
                sort="id",
                page=page,
                per_page=100,
            )
            records.extend(result.get("items", []))
            if page >= result.get("totalPages", 1):
                return records
            if not result.get("items"):
                raise HTTPException(502, "Incomplete pagination")
            page += 1

    @booking_policy.serialize_schedule
    async def create_booking(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        await self._booking_slot(pb, token, site_id, data)
        data = {**data, "date": booking_policy.booking_date(data["date"]).isoformat()}
        booking_id = f"booking_{uuid4().hex}"
        await pb.create_record(
            "bookings",
            {
                "booking_id": booking_id,
                "site_id": site_id,
                **data,
                "status": "pending",
                "deleted_at": "",
            },
            token=token,
            user_id=user_id,
        )
        return await self.get_booking(pb, token, booking_id, site_id)

    @booking_policy.serialize_schedule
    async def update_booking(
        self,
        pb: PocketBaseClient,
        token: str,
        booking_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        scope = f" && site_id={filter_value(site_id)}" if site_id else ""
        booking = await pb.find_one_by_filter(
            "bookings",
            f'booking_id={filter_value(booking_id)} && deleted_at=""{scope}',
            token=token,
        )
        if "status" in data:
            booking_policy.validate_status(booking.get("status"), data["status"])
        schedule_fields = {"date", "start_time", "end_time", "property_id"}
        if schedule_fields.intersection(data) and booking.get("status") in {
            "completed",
            "cancelled",
        }:
            raise HTTPException(409, "Terminal bookings cannot be rescheduled")
        merged = {**booking, **data}
        if merged.get("status") in {"pending", "confirmed"}:
            await self._booking_slot(pb, token, booking["site_id"], merged, booking_id)
        if "date" in data:
            data = {
                **data,
                "date": booking_policy.booking_date(data["date"]).isoformat(),
            }
        if "property_id" in data:
            prop = await self._properties(
                pb, token, booking["site_id"], [data["property_id"]]
            )
            if (
                data["property_id"] not in prop
                or prop[data["property_id"]].get("type") != "spa_service"
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Booking property must be a spa_service on the site",
                )
        await pb.update_record(
            "bookings", booking["id"], data, token=token, user_id=user_id
        )
        return await self.get_booking(pb, token, booking_id, booking["site_id"])

    @booking_policy.serialize_schedule
    async def delete_booking(
        self,
        pb: PocketBaseClient,
        token: str,
        booking_id: str,
        user_id: str | None = None,
    ) -> None:
        booking = await pb.find_one_by_filter(
            "bookings",
            f'booking_id={filter_value(booking_id)} && deleted_at=""',
            token=token,
        )
        if booking.get("status") not in {"pending", "cancelled"}:
            raise HTTPException(
                409,
                "Cancel a confirmed booking before deleting it; completed history is retained",
            )
        await pb.update_record(
            "bookings",
            booking["id"],
            {"deleted_at": datetime.now(UTC).isoformat()},
            token=token,
            user_id=user_id,
        )

    async def list_availability(
        self, pb: PocketBaseClient, token: str, site_id: str, **params: Any
    ) -> dict[str, Any]:
        parts = [f"site_id={filter_value(site_id)}"]
        if params.get("property_id"):
            parts.append(f"property_id={filter_value(params['property_id'])}")
        if params.get("day_of_week"):
            parts.append(f"day_of_week={filter_value(params['day_of_week'])}")
        return await pb.list_records(
            "availability",
            token=token,
            filter=" && ".join(parts),
            sort="property_id,day_of_week,start_time",
            page=params.get("page", 1),
            per_page=params.get("per_page", 50),
        )

    @booking_policy.serialize_schedule
    async def create_availability(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        booking_policy.validate_availability(data)
        properties = await self._properties(pb, token, site_id, [data["property_id"]])
        if (
            data["property_id"] not in properties
            or properties[data["property_id"]].get("type") != "spa_service"
        ):
            raise HTTPException(
                status_code=422,
                detail="Availability property must be a spa_service on the site",
            )
        return await pb.create_record(
            "availability",
            {
                "availability_id": f"availability_{uuid4().hex}",
                "site_id": site_id,
                **data,
            },
            token=token,
            user_id=user_id,
        )

    @booking_policy.serialize_schedule
    async def update_availability(
        self,
        pb: PocketBaseClient,
        token: str,
        availability_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        record = await pb.find_one_by_filter(
            "availability",
            f"availability_id={filter_value(availability_id)}",
            token=token,
        )
        booking_policy.validate_availability({**record, **data})
        if "property_id" in data:
            properties = await self._properties(
                pb, token, record["site_id"], [data["property_id"]]
            )
            if (
                data["property_id"] not in properties
                or properties[data["property_id"]].get("type") != "spa_service"
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Availability property must be a spa_service on the site",
                )
        return await pb.update_record(
            "availability", record["id"], data, token=token, user_id=user_id
        )

    @booking_policy.serialize_schedule
    async def delete_availability(
        self, pb: PocketBaseClient, token: str, availability_id: str
    ) -> None:
        record = await pb.find_one_by_filter(
            "availability",
            f"availability_id={filter_value(availability_id)}",
            token=token,
        )
        await pb.delete_record("availability", record["id"], token=token)

    async def _properties(
        self, pb: PocketBaseClient, token: str, site_id: str, property_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        ids = sorted({value for value in property_ids if value})
        if not ids:
            return {}
        records = []
        for offset in range(0, len(ids), 100):
            clauses = " || ".join(
                f"property_id={filter_value(value)}"
                for value in ids[offset : offset + 100]
            )
            records.extend(
                await self._all_records(
                    pb,
                    token,
                    "properties",
                    f'site_id={filter_value(site_id)} && ({clauses}) && deleted_at=""',
                )
            )
        return {record["property_id"]: record for record in records}
