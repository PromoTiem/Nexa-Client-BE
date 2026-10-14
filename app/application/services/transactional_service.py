from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.application.services.order_policy import (
    finite_decimal,
    require_editable,
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
        total = sum(
            float(item["quantity"]) * float(item["unit_price"]) for item in items
        )
        await pb.create_record(
            "orders",
            {
                "order_id": order_id,
                "site_id": site_id,
                "status": "pending",
                "total": total,
                "deleted_at": "",
                **data,
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
                    "total_price": float(item["quantity"]) * float(item["unit_price"]),
                    "variation": item.get("variation"),
                    "metadata": item.get("metadata"),
                },
                token=token,
                user_id=user_id,
            )
        return await self.get_order(pb, token, order_id, site_id)

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
        await pb.update_record(
            "orders",
            order["id"],
            {"deleted_at": datetime.now(UTC).isoformat()},
            token=token,
            user_id=user_id,
        )

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
                "total_price": float(data["quantity"]) * float(data["unit_price"]),
                **data,
            },
            token=token,
            user_id=user_id,
        )
        return item

    async def delete_order_item(
        self, pb: PocketBaseClient, token: str, item_id: str, user_id: str | None = None
    ) -> None:
        item = await pb.find_one_by_filter(
            "order_items", f"item_id={filter_value(item_id)}", token=token
        )
        order = await pb.find_one_by_filter(
            "orders",
            f'order_id={filter_value(item["order_id"])} && deleted_at=""',
            token=token,
        )
        require_editable(order)
        await pb.delete_record("order_items", item["id"], token=token)

    async def list_payments(
        self, pb: PocketBaseClient, token: str, order_id: str
    ) -> list[dict[str, Any]]:
        await pb.find_one_by_filter(
            "orders", f'order_id={filter_value(order_id)} && deleted_at=""', token=token
        )
        return await self._order_children(pb, token, "payments", order_id)

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

    async def create_booking(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        property_id = data["property_id"]
        prop = await self._properties(pb, token, site_id, [property_id])
        if property_id not in prop or prop[property_id].get("type") != "spa_service":
            raise HTTPException(
                status_code=422,
                detail="Booking property must be a spa_service on the site",
            )
        booking_id = f"booking_{uuid4().hex}"
        await pb.create_record(
            "bookings",
            {
                "booking_id": booking_id,
                "site_id": site_id,
                "status": "pending",
                "deleted_at": "",
                **data,
            },
            token=token,
            user_id=user_id,
        )
        return await self.get_booking(pb, token, booking_id, site_id)

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

    async def create_availability(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        data: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
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
        clauses = " || ".join(f"property_id={filter_value(value)}" for value in ids)
        result = await pb.list_records(
            "properties",
            token=token,
            filter=f'site_id={filter_value(site_id)} && ({clauses}) && deleted_at=""',
            per_page=min(len(ids), 100),
        )
        return {record["property_id"]: record for record in result.get("items", [])}
