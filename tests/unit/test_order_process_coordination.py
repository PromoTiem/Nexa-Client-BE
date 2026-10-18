"""Independent-process service coordination with shared synthetic persistence.

No network or production records. Tests the actual order/site lock decorators;
real PocketBase and authentication acceptance remain separate.
"""

import asyncio
import multiprocessing
import sqlite3

import pytest


def worker(db, operation, entered, release, result):
    from fastapi import HTTPException

    from app.application.services.booking_policy import serialize_schedule
    from app.application.services.order_policy import serialize_order
    from app.infrastructure.operation_lock import operation_lock

    class Persistence:
        async def find_one_by_filter(self, collection, filter_expr, **kwargs):
            if collection == "orders":
                return {"site_id": "race_site", "order_id": "race_order"}
            with sqlite3.connect(db) as connection:
                retained = connection.execute("SELECT retained FROM state").fetchone()[
                    0
                ]
            return {
                "site_id": "race_site",
                "config": {"_nexa_lifecycle": {"deleted_at": "now"}}
                if retained
                else {},
            }

    async def write():
        entered.set()
        for _ in range(500):
            if release.is_set():
                break
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("Barrier timed out")
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE state SET writes = writes + 1")

    class Commands:
        @serialize_order
        async def mutate(self, pb, token, order_id):
            await write()

        @serialize_schedule
        async def create(self, pb, token, site_id):
            await write()

    async def run():
        pb = Persistence()
        try:
            if operation == "retain":
                async with operation_lock("site:race_site"):
                    entered.set()
                    for _ in range(500):
                        if release.is_set():
                            break
                        await asyncio.sleep(0.01)
                    else:
                        raise TimeoutError("Barrier timed out")
                    with sqlite3.connect(db) as connection:
                        connection.execute("UPDATE state SET retained = 1")
                result.put(200)
            else:
                command = Commands()
                if operation == "create":
                    await command.create(pb, "synthetic", "race_site")
                else:
                    await command.mutate(pb, "synthetic", "race_order")
                result.put(200)
        except HTTPException as error:
            result.put(error.status_code)

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["create", "mutate"])
@pytest.mark.parametrize("retention_first", [True, False])
def test_order_site_lock_coordinates_independent_processes(
    tmp_path, operation, retention_first
):
    db = str(tmp_path / "state.db")
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE state (retained INTEGER, writes INTEGER)")
        connection.execute("INSERT INTO state VALUES (0,0)")
    ctx = multiprocessing.get_context("spawn")
    first_entered, second_entered = ctx.Event(), ctx.Event()
    first_release, second_release = ctx.Event(), ctx.Event()
    second_release.set()
    first_result, second_result = ctx.Queue(), ctx.Queue()
    first_op, second_op = (
        ("retain", operation) if retention_first else (operation, "retain")
    )
    first = ctx.Process(
        target=worker, args=(db, first_op, first_entered, first_release, first_result)
    )
    second = ctx.Process(
        target=worker,
        args=(db, second_op, second_entered, second_release, second_result),
    )
    try:
        first.start()
        assert first_entered.wait(10), "First process failed to acquire lock"
        second.start()
        assert not second_entered.wait(0.3), "Second process bypassed held site lock"
        first_release.set()
        first.join(15)
        second.join(15)
        assert first.exitcode == second.exitcode == 0
        assert first_result.get(timeout=2) == 200
        assert second_result.get(timeout=2) == (404 if retention_first else 200)
        with sqlite3.connect(db) as connection:
            assert connection.execute(
                "SELECT retained,writes FROM state"
            ).fetchone() == (1, 0 if retention_first else 1)
    finally:
        for process in (first, second):
            if process.pid and process.is_alive():
                process.terminate()
                process.join(5)
