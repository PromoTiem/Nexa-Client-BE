"""Server-side pricing for the public ecommerce checkout.

The storefront cart lives in the browser, so its prices cannot be trusted. The
server prices every line from the site's own published ``product`` properties;
the public order route stores these prices and computes the charge from them.

``EcommerceSettings.prices`` (the Nexa-FE admin demo catalogue) is used only for
a site that has no product records at all.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.application.services.transactional_service import TransactionalService
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.pocketbase.filters import sanitize_filter_value

VARIANT_SEPARATOR = "::"
"""Storefront cart ids are ``<slug>`` or ``<slug>::<variant name>``."""


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


def _whole_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _unit_price(product: dict[str, Any], variant: str | None) -> int | None:
    """Product ``price`` field; a variant uses its own ``price`` or adds ``delta``."""
    fields = {
        field.get("key"): field.get("value")
        for field in product.get("fields") or []
        if isinstance(field, dict)
    }
    base = _whole_number(fields.get("price"))
    if base is None or variant is None:
        return base
    variants = fields.get("variants")
    row = next(
        (
            row
            for row in (variants if isinstance(variants, list) else [])
            if isinstance(row, dict) and row.get("name") == variant
        ),
        None,
    )
    if row is None:
        return None
    if row.get("price") is not None:
        return _whole_number(row["price"])
    delta = _whole_number(row.get("delta", 0))
    return None if delta is None else base + delta


def _quoted(value: str) -> str:
    return f'"{sanitize_filter_value(value)}"'


async def site_catalogue_prices(
    pb: PocketBaseClient,
    site_id: str,
    product_ids: Iterable[str],
    *,
    fallback: Mapping[str, int],
) -> Mapping[str, int]:
    """Current unit price for each requested cart id the site sells.

    An id matches a published, non-deleted ``product`` of this site by
    ``property_id`` or ``slug``; an id that matches two products is not priced.
    Ids left out of the result are rejected by ``price_order`` as unknown.
    ``fallback`` applies only when the site has no product records at all.
    """
    requested = set(product_ids)
    bases = sorted({pid.partition(VARIANT_SEPARATOR)[0] for pid in requested} - {""})
    site_clause = f'site_id={_quoted(site_id)} && type="product" && deleted_at=""'
    service = TransactionalService()
    products: list[dict[str, Any]] = []
    for offset in range(0, len(bases), 50):
        ids = " || ".join(
            f"property_id={_quoted(pid)} || slug={_quoted(pid)}"
            for pid in bases[offset : offset + 50]
        )
        products.extend(
            await service._all_records(
                pb,
                pb._static_token,
                "properties",
                f'{site_clause} && status="published" && ({ids})',
            )
        )

    prices: dict[str, int] = {}
    for pid in requested:
        base, separator, variant = pid.partition(VARIANT_SEPARATOR)
        matches = {
            product["property_id"]: product
            for product in products
            if base and base in (product.get("property_id"), product.get("slug"))
        }
        if len(matches) != 1 or (separator and not variant):
            continue
        price = _unit_price(
            next(iter(matches.values())), variant if separator else None
        )
        if price is not None:
            prices[pid] = price

    if products:
        return prices
    any_product = await pb.list_records(
        "properties",
        token=pb._static_token,
        filter=site_clause,
        page=1,
        per_page=1,
    )
    return prices if any_product.get("items") else fallback
