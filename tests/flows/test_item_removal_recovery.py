from fastapi import HTTPException

from tests.flows.test_transaction_flow import database, flow, make_order  # noqa: F401


async def test_scoped_removal_retry_repairs_failed_total(flow, monkeypatch):  # noqa: F811
    client, pb, _, site, prop = flow
    order = await make_order(client, site, prop)
    order_id = order["order_id"]
    added = await client.post(
        f"/orders/{order_id}/items",
        json={
            "property_id": prop["property_id"],
            "quantity": 1,
            "unit_price": 10,
        },
    )
    assert added.status_code == 201, added.text
    original = pb.update_record
    failed = False

    async def interrupted(collection, record_id, data, **kwargs):
        nonlocal failed
        if collection == "orders" and "total" in data and not failed:
            failed = True
            raise HTTPException(503, "Injected total failure")
        return await original(collection, record_id, data, **kwargs)

    monkeypatch.setattr(pb, "update_record", interrupted)
    path = f"/orders/{order_id}/items/{added.json()['item_id']}"
    assert (await client.delete(path)).status_code == 503
    assert (await client.delete(path)).status_code == 204
    assert (await client.delete(path)).status_code == 204
    persisted = await pb.find_one_by_filter("orders", f'order_id="{order_id}"')
    assert persisted["total"] == 0.3
    final = f"/orders/{order_id}/items/{order['items'][0]['item_id']}"
    assert (await client.delete(final)).status_code == 409
    # Authorization occurs before absent-item success.
    assert (await client.delete("/orders/unknown/items/unknown")).status_code == 404
