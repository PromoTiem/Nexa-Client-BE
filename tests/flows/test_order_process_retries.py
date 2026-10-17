"""Actual transaction services in independent processes against disposable PB."""

import asyncio
import multiprocessing

from tests.flows.test_transaction_flow import database, flow  # noqa: F401


def command(
    base, token, site_id, property_id, operation, order_id, ready, start, result
):
    from app.application.services.transactional_service import TransactionalService
    from app.infrastructure.pocketbase.client import PocketBaseClient

    async def run():
        pb = PocketBaseClient(base, static_token=token, max_retries=1)
        service = TransactionalService()
        ready.set()
        if not start.wait(15):
            raise TimeoutError("Process barrier")
        item = {"property_id": property_id, "quantity": 1, "unit_price": 5}
        if operation == "create":
            row = await service.create_order(
                pb,
                token,
                site_id,
                {
                    "currency": "USD",
                    "items": [item],
                    "idempotency_key": "process_create_001",
                },
            )
            result.put(row["order_id"])
        elif operation == "item":
            row = await service.add_order_item(
                pb,
                token,
                order_id,
                {
                    **item,
                    "idempotency_key": "process_item_001",
                },
            )
            result.put(row["item_id"])
        else:
            row = await service.fake_payment(pb, token, order_id, "process_payment_001")
            result.put(row["payment_id"])

    asyncio.run(run())


def compete(base, token, site_id, property_id, operation, order_id=None):
    ctx = multiprocessing.get_context("spawn")
    start, result = ctx.Event(), ctx.Queue()
    ready = [ctx.Event() for _ in range(3)]
    processes = [
        ctx.Process(
            target=command,
            args=(
                base,
                token,
                site_id,
                property_id,
                operation,
                order_id,
                signal,
                start,
                result,
            ),
        )
        for signal in ready
    ]
    try:
        for process in processes:
            process.start()
        assert all(signal.wait(15) for signal in ready)
        start.set()
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        ids = [result.get(timeout=5) for _ in processes]
        assert len(set(ids)) == 1
        return ids[0]
    finally:
        for process in processes:
            if process.pid and process.is_alive():
                process.terminate()
                process.join(5)


async def test_real_persistence_cross_process_retries(database, flow):  # noqa: F811
    base, token, _ = database
    _, pb, _, site, prop = flow
    args = (base, token, site["site_id"], prop["property_id"])
    order_id = await asyncio.to_thread(compete, *args, "create")
    await asyncio.to_thread(compete, *args, "item", order_id)
    await asyncio.to_thread(compete, *args, "payment", order_id)
    items = await pb.list_records("order_items", filter=f'order_id="{order_id}"')
    payments = await pb.list_records("payments", filter=f'order_id="{order_id}"')
    order = await pb.find_one_by_filter("orders", f'order_id="{order_id}"')
    assert items["totalItems"] == 2
    assert payments["totalItems"] == 1
    assert order["status"] == "paid" and order["total"] == 10
