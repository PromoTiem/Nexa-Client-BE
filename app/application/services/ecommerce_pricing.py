"""Server-side pricing for the public ecommerce checkout.

The storefront cart lives in the browser, so its prices cannot be trusted. The
``EcommerceSettings.prices`` catalogue is the server authority; the public order
route stores these prices and computes the charge from them.

The demo catalogue mirrors Nexa-FE's ``ecommerceCatalogue.ts`` until the live
product/catalogue API exists (see the storefront comment). Keep the two in sync
while the demo is the only storefront using this endpoint.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


class PricingError(ValueError):
    """A request cannot be priced from the server catalogue."""


class UnknownProductError(PricingError):
    def __init__(self, product_id: str) -> None:
        super().__init__(f"Unknown product: {product_id}")
        self.product_id = product_id


class OrderTotalMismatchError(PricingError):
    def __init__(self, expected: int, received: int) -> None:
        super().__init__(f"Expected total {expected}, received {received}")
        self.expected = expected
        self.received = received


@dataclass(frozen=True)
class PricedLine:
    product_id: str
    quantity: int
    unit_price: int
    total_price: int


@dataclass(frozen=True)
class OrderPricing:
    lines: tuple[PricedLine, ...]
    subtotal: int
    shipping_fee: int
    total: int


def price_order(
    lines: Iterable[tuple[str, int]],
    *,
    prices: Mapping[str, int],
    free_shipping_threshold: int,
    shipping_fee: int,
    requested_total: int | None = None,
) -> OrderPricing:
    """Price an order from the catalogue, ignoring every client-supplied price.

    ``requested_total`` is only a consistency check: the FE shows a total before
    submitting, so a mismatch means the catalogue changed (or the request was
    tampered with) and the shopper must refresh. Omitting it is allowed; the
    server still computes the real charge.
    """
    priced_lines: list[PricedLine] = []
    subtotal = 0
    for product_id, quantity in lines:
        unit_price = prices.get(product_id)
        if unit_price is None or unit_price <= 0:
            raise UnknownProductError(product_id)
        line_total = quantity * unit_price
        subtotal += line_total
        priced_lines.append(
            PricedLine(
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
                total_price=line_total,
            )
        )

    shipping = 0 if subtotal >= free_shipping_threshold else shipping_fee
    total = subtotal + shipping
    if requested_total is not None and requested_total != total:
        raise OrderTotalMismatchError(expected=total, received=requested_total)
    return OrderPricing(
        lines=tuple(priced_lines),
        subtotal=subtotal,
        shipping_fee=shipping,
        total=total,
    )
