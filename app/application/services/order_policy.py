"""Order state and finite-number validation shared by transaction commands."""

from decimal import Decimal, InvalidOperation
from functools import wraps
from inspect import signature
from typing import Any

from fastapi import HTTPException

from app.application.access import assert_site_active
from app.infrastructure.operation_lock import operation_lock
from app.infrastructure.pocketbase.filters import sanitize_filter_value

TRANSITIONS = {
    "pending": {"paid", "cancelled"},
    "paid": {"fulfilled", "cancelled"},
    "fulfilled": set(),
    "cancelled": set(),
}


def validate_transition(current: str, target: Any) -> None:
    if target not in TRANSITIONS:
        raise HTTPException(422, "Invalid order status")
    if current not in TRANSITIONS or (
        target != current and target not in TRANSITIONS[current]
    ):
        raise HTTPException(409, "Invalid order status transition")


def require_editable(order: dict[str, Any]) -> None:
    if order.get("status") != "pending":
        raise HTTPException(409, "Only pending orders can change items")


def finite_decimal(value: Any, *, positive: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, "Invalid monetary value or quantity") from None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise HTTPException(422, "Invalid monetary value or quantity")
    return number


def money(value: Any) -> float:
    amount = finite_decimal(value)
    if amount > Decimal("1000000000000"):
        raise HTTPException(422, "Amount exceeds supported limit")
    return float(amount)


def line_total(item: dict[str, Any]) -> Decimal:
    quantity = finite_decimal(item["quantity"], positive=True)
    price = finite_decimal(item["unit_price"])
    total = quantity * price
    money(total)
    return total


def serialize_order(method):
    """Coordinate API mutations of an order on the shared application host."""
    parameters = signature(method)

    @wraps(method)
    async def wrapped(*args, **kwargs):
        bound = parameters.bind(*args, **kwargs).arguments
        pb, token = bound["pb"], bound["token"]
        order = await pb.find_one_by_filter(
            "orders",
            f'order_id="{sanitize_filter_value(bound["order_id"])}" && deleted_at=""',
            token=token,
        )
        site_id = order["site_id"]
        async with operation_lock("site:" + site_id):
            site = await pb.find_one_by_filter(
                "sites", f'site_id="{sanitize_filter_value(site_id)}"', token=token
            )
            assert_site_active(site)
            async with operation_lock("order:" + bound["order_id"]):
                return await method(*args, **kwargs)

    return wrapped
