import pytest

from app.application.services.ecommerce_pricing import (
    OrderTotalMismatchError,
    UnknownProductError,
    price_order,
)
from app.config import EcommerceSettings

PRICES = {"p-ly-gom": 320_000, "p-tham-len": 1_250_000}


def test_prices_come_from_the_catalogue():
    result = price_order(
        [("p-ly-gom", 2)],
        prices=PRICES,
        free_shipping_threshold=500_000,
        shipping_fee=30_000,
    )

    assert result.subtotal == 640_000
    assert result.shipping_fee == 0
    assert result.total == 640_000
    assert result.lines[0].unit_price == 320_000
    assert result.lines[0].total_price == 640_000


def test_shipping_fee_applies_below_threshold():
    result = price_order(
        [("p-ly-gom", 1)],
        prices=PRICES,
        free_shipping_threshold=500_000,
        shipping_fee=30_000,
    )

    assert result.subtotal == 320_000
    assert result.shipping_fee == 30_000
    assert result.total == 350_000


def test_shipping_is_free_at_the_threshold():
    result = price_order(
        [("p-ly-gom", 1)],
        prices=PRICES,
        free_shipping_threshold=320_000,
        shipping_fee=30_000,
    )

    assert result.shipping_fee == 0
    assert result.total == 320_000


def test_requested_total_mismatch_raises():
    with pytest.raises(OrderTotalMismatchError) as error:
        price_order(
            [("p-ly-gom", 1)],
            prices=PRICES,
            free_shipping_threshold=500_000,
            shipping_fee=30_000,
            requested_total=1_000,
        )

    assert error.value.expected == 350_000
    assert error.value.received == 1_000


def test_unknown_product_raises():
    with pytest.raises(UnknownProductError) as error:
        price_order(
            [("p-missing", 1)],
            prices=PRICES,
            free_shipping_threshold=500_000,
            shipping_fee=30_000,
        )

    assert error.value.product_id == "p-missing"


@pytest.mark.parametrize("price", [0, -1])
def test_non_positive_catalogue_price_is_rejected(price):
    with pytest.raises(UnknownProductError):
        price_order(
            [("p-bad", 1)],
            prices={"p-bad": price},
            free_shipping_threshold=500_000,
            shipping_fee=30_000,
        )


def test_omitted_requested_total_is_allowed():
    result = price_order(
        [("p-ly-gom", 1)],
        prices=PRICES,
        free_shipping_threshold=500_000,
        shipping_fee=30_000,
    )

    assert result.total == 350_000


def test_multiple_lines_keep_their_order():
    result = price_order(
        [("p-ly-gom", 1), ("p-tham-len", 1)],
        prices=PRICES,
        free_shipping_threshold=500_000,
        shipping_fee=30_000,
    )

    assert result.subtotal == 1_570_000
    assert result.shipping_fee == 0
    assert result.total == 1_570_000
    assert [line.product_id for line in result.lines] == ["p-ly-gom", "p-tham-len"]


def test_default_catalogue_matches_the_demo_storefront():
    settings = EcommerceSettings()

    assert settings.prices["p-ly-gom"] == 320_000
    assert settings.prices["p-tham-len"] == 1_250_000
    assert settings.free_shipping_threshold == 500_000
    assert settings.shipping_fee == 30_000
