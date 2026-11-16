"""Public orders are priced from the site's own product records.

The storefront cart sends ``<slug>`` or ``<slug>::<variant name>`` as the item
``property_id`` (Nexa-Builders ``product_detail`` / ``product_grid`` blocks). A
variant adds its ``delta`` to the product price, or uses its own ``price``.
"""

from typing import Any

import httpx
import pytest

from app.config import EcommerceSettings
from tests.fake_pocketbase import FakePocketBase
from tests.unit.test_public_order import SITE_ID, create_test_app

OTHER_SITE = "site_beta_456"


def product(
    slug: str,
    price: Any,
    *,
    site_id: str = SITE_ID,
    status: str = "published",
    deleted_at: str = "",
    variants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"key": "price", "label": "Price", "type": "number", "value": price},
        {"key": "stock", "label": "Stock", "type": "number", "value": 5},
    ]
    if variants is not None:
        fields.append(
            {
                "key": "variants",
                "label": "Variants",
                "type": "repeater",
                "value": variants,
            }
        )
    return {
        "id": f"rec_{site_id}_{slug}",
        "property_id": "prod_" + slug.replace("-", "_"),
        "site_id": site_id,
        "type": "product",
        "slug": slug,
        "name": slug.title(),
        "status": status,
        "deleted_at": deleted_at,
        "fields": fields,
        "groups": [],
    }


CATALOGUE = [
    product(
        "linen-shirt",
        690_000,
        variants=[
            {"name": "Natural", "delta": 0},
            {"name": "Indigo", "delta": 30_000},
            {"name": "Sand Washed", "price": 750_000},
        ],
    ),
    product("ceramic-mug", 180_000),
    product("foreign-lamp", 400_000, site_id=OTHER_SITE),
    product("draft-vase", 300_000, status="draft"),
    product("old-chair", 900_000, deleted_at="2026-11-01T00:00:00Z"),
    {**product("not-a-product", 100_000), "type": "spa_service"},
]


def shop_settings() -> EcommerceSettings:
    return EcommerceSettings(
        prices={"p-ly-gom": 320_000},
        free_shipping_threshold=500_000,
        shipping_fee=30_000,
    )


async def place(
    pb: FakePocketBase,
    items: list[tuple[str, int]],
    total: int | None,
    *,
    phone: str | None = "0901234567",
) -> httpx.Response:
    app = create_test_app(pb, ecommerce=shop_settings())  # type: ignore[arg-type]
    payload: dict[str, Any] = {
        "customer_name": "Guest",
        "customer_phone": phone,
        "payment_method": "cod",
        "items": [
            {"property_id": pid, "quantity": qty, "unit_price": 1} for pid, qty in items
        ],
    }
    if total is not None:
        payload["total"] = total
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(f"/public/sites/{SITE_ID}/orders", json=payload)


def created(pb: FakePocketBase, collection: str) -> list[dict[str, Any]]:
    return [data for name, data in pb.created if name == collection]


@pytest.mark.parametrize("product_id", ["linen-shirt", "prod_linen_shirt"])
async def test_base_price_comes_from_the_site_product(product_id: str) -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(pb, [(product_id, 1)], 690_000)

    assert response.status_code == 201, response.text
    assert response.json()["total"] == 690_000
    [item] = created(pb, "order_items")
    assert item["property_id"] == product_id
    assert item["unit_price"] == 690_000


async def test_variant_delta_is_added_to_the_product_price() -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(pb, [("linen-shirt::Indigo", 2)], 1_440_000)

    assert response.status_code == 201, response.text
    [item] = created(pb, "order_items")
    assert item["unit_price"] == 720_000
    assert item["total_price"] == 1_440_000


async def test_variant_own_price_replaces_the_product_price() -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(pb, [("linen-shirt::Sand Washed", 1)], 750_000)

    assert response.status_code == 201, response.text
    assert created(pb, "order_items")[0]["unit_price"] == 750_000


async def test_mixed_cart_with_shipping_below_threshold() -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(pb, [("ceramic-mug", 2)], 390_000)

    assert response.status_code == 201, response.text
    [order] = created(pb, "orders")
    assert order["total"] == 390_000
    assert order["metadata"]["subtotal"] == 360_000
    assert order["metadata"]["shipping_fee"] == 30_000
    assert created(pb, "payments")[0]["amount"] == 390_000


async def test_free_shipping_at_threshold() -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(
        pb, [("linen-shirt::Natural", 1), ("ceramic-mug", 1)], 870_000
    )

    assert response.status_code == 201, response.text
    assert created(pb, "orders")[0]["metadata"]["shipping_fee"] == 0


@pytest.mark.parametrize(
    "product_id",
    [
        "no-such-product",
        "linen-shirt::Purple",
        "ceramic-mug::Large",
        "linen-shirt::",
        "::Indigo",
        "foreign-lamp",
        "prod_foreign_lamp",
        "draft-vase",
        "old-chair",
        "not-a-product",
        "p-ly-gom",
    ],
)
async def test_unresolvable_product_is_rejected_before_anything_is_written(
    product_id: str,
) -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(pb, [("ceramic-mug", 1), (product_id, 1)], None)

    assert response.status_code == 422
    assert response.json()["detail"] == f"Unknown product: {product_id}"
    assert pb.created == []


async def test_total_mismatch_is_rejected() -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(pb, [("linen-shirt::Indigo", 1)], 690_000)

    assert response.status_code == 422
    assert "Order total does not match current prices" in response.text
    assert pb.created == []


@pytest.mark.parametrize(
    "bad_price", [None, "", "690000", 0, -5, 12.5, True, [690_000]]
)
async def test_product_without_a_usable_price_is_unknown(bad_price: Any) -> None:
    pb = FakePocketBase(properties=[product("odd-item", bad_price)])

    response = await place(pb, [("odd-item", 1)], None)

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown product: odd-item"


async def test_whole_number_float_price_is_accepted() -> None:
    pb = FakePocketBase(properties=[product("float-item", 600_000.0)])

    response = await place(pb, [("float-item", 1)], 600_000)

    assert response.status_code == 201, response.text


async def test_demo_prices_apply_only_when_the_site_has_no_products() -> None:
    pb = FakePocketBase(properties=[product("foreign-lamp", 1, site_id=OTHER_SITE)])

    response = await place(pb, [("p-ly-gom", 1)], 350_000)

    assert response.status_code == 201, response.text
    assert created(pb, "order_items")[0]["unit_price"] == 320_000


async def test_draft_only_catalogue_does_not_fall_back_to_demo_prices() -> None:
    pb = FakePocketBase(properties=[product("draft-vase", 300_000, status="draft")])

    response = await place(pb, [("p-ly-gom", 1)], 350_000)

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown product: p-ly-gom"


async def test_ambiguous_id_matching_two_products_is_rejected() -> None:
    first = product("shared-id", 100_000)
    second = {**product("other", 200_000), "property_id": "shared-id"}
    pb = FakePocketBase(properties=[first, second])

    response = await place(pb, [("shared-id", 1)], None)

    assert response.status_code == 422


async def test_catalogue_larger_than_one_page_is_read_completely() -> None:
    many = [product(f"item-{n:03d}", 10_000 + n) for n in range(250)]
    pb = FakePocketBase(properties=many)

    response = await place(pb, [("item-249", 1), ("item-000", 1)], None)

    assert response.status_code == 201, response.text
    assert response.json()["total"] == 10_249 + 10_000 + 30_000


@pytest.mark.parametrize(
    "phone",
    ["0901234567", "+84901234567", "+84 901 234 567", "090-123.4567", "", None],
)
async def test_valid_or_absent_order_phone_is_accepted(phone: str | None) -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(pb, [("linen-shirt", 1)], 690_000, phone=phone)

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "phone",
    ["abc", "12345", "84901234567", "+8490123456", "09012345678", "0901 23x 567"],
)
async def test_invalid_order_phone_is_rejected(phone: str) -> None:
    pb = FakePocketBase(properties=CATALOGUE)

    response = await place(pb, [("linen-shirt", 1)], 690_000, phone=phone)

    assert response.status_code == 422
    assert "phone" in response.json()["detail"].lower()
    assert pb.created == []
