"""Order state and finite-number validation shared by transaction commands."""

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

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
