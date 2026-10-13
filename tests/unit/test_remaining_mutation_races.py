import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.application.services.public_submission_service import create_booking
from app.infrastructure.operation_lock import operation_lock
from app.interface.dto.build import BuildCreateRequest, BuildUpdateRequest
from app.interface.dto.property import PropertyCreateRequest, PropertyUpdateRequest
from app.interface.routes import build
from app.interface.routes import property as properties
from tests.unit.test_retained_consumer import context


@pytest.mark.parametrize(
    "operation",
    [
        "property_create",
        "property_update",
        "property_delete",
        "public",
        "build_update",
        "build_delete",
    ],
)
async def test_mutation_waits_and_rechecks_parent(operation):
    pb = AsyncMock()
    parent = {"id": "site", "site_id": "mutation-race", "tenant_id": "tr", "config": {}}
    record = {
        "id": "r",
        "property_id": "p",
        "build_id": "b",
        "site_id": "mutation-race",
        "status": "failed",
        "name": "test",
    }

    async def find(collection, *args, **kwargs):
        if collection == "sites":
            return parent
        if collection == "tenants":
            return {"id": "tr", "tenant_id": "tenant"}
        return record.copy()

    pb.find_one_by_filter.side_effect = find
    started = asyncio.Event()

    async def request():
        started.set()
        if operation == "property_create":
            return await properties.create_property(
                "mutation-race",
                PropertyCreateRequest(property_id="p", name="test", type="post"),
                context(),
                pb,
            )
        if operation == "property_update":
            return await properties.update_property(
                "p", PropertyUpdateRequest(name="changed"), context(), pb
            )
        if operation == "property_delete":
            return await properties.delete_property("p", context(), pb)
        if operation == "public":
            return await create_booking(pb, "mutation-race", {})
        if operation == "build_update":
            return await build.update_build(
                "b", BuildUpdateRequest(content_id="changed"), context(), pb
            )
        return await build.delete_build("b", context(), pb)

    async with operation_lock("site:mutation-race"):
        task = asyncio.create_task(request())
        await started.wait()
        # The task must reach the lock before the parent is changed.
        await asyncio.sleep(0.03)
        was_waiting = not task.done()
        parent["config"] = {"_nexa_lifecycle": {"deleted_at": "now"}}
    try:
        await task
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        pytest.fail("retained mutation succeeded")
    assert was_waiting
    pb.create_record.assert_not_awaited()
    pb.update_record.assert_not_awaited()
    pb.delete_record.assert_not_awaited()


@pytest.mark.parametrize(
    "model,payload",
    [(BuildCreateRequest, {"build_id": "b", "site_id": "s"}), (BuildUpdateRequest, {})],
)
def test_attempt_metadata_is_server_owned(model, payload):
    with pytest.raises(ValidationError):
        model(**payload, config={"_nexa_attempt": {"token": "forged"}})


def build_database(status="failed", config=None):
    pb = AsyncMock()
    record = {
        "id": "r",
        "site_id": "s",
        "build_id": "b",
        "status": status,
        "config": config or {},
    }

    async def find(collection, **kwargs):
        if collection == "sites":
            return {"site_id": "s", "tenant_id": "tr", "config": {}}
        if collection == "tenants":
            return {"id": "tr", "tenant_id": "tenant"}
        return record.copy()

    pb.find_one_by_filter.side_effect = find
    pb.update_record.side_effect = lambda **kw: {**record, **kw["data"]}
    return pb


@pytest.mark.parametrize("operation", ["patch", "delete"])
async def test_active_build_cannot_be_mutated(operation):
    pb = build_database("building")
    with pytest.raises(HTTPException) as exc:
        if operation == "patch":
            await build.update_build(
                "b", BuildUpdateRequest(status="failed"), context(), pb
            )
        else:
            await build.delete_build("b", context(), pb)
    assert exc.value.status_code == 409
    pb.update_record.assert_not_awaited()
    pb.delete_record.assert_not_awaited()


@pytest.mark.parametrize("status", ["building", "completed"])
async def test_executor_owned_status_rejected(status):
    pb = build_database()
    with pytest.raises(HTTPException) as exc:
        await build.update_build("b", BuildUpdateRequest(status=status), context(), pb)
    assert exc.value.status_code == 409
    pb.update_record.assert_not_awaited()


@pytest.mark.parametrize("config", [None, {"pages": []}])
async def test_config_replacement_preserves_attempt(config):
    pb = build_database(config={"_nexa_attempt": {"attempt_id": "server"}})
    await build.update_build("b", BuildUpdateRequest(config=config), context(), pb)
    assert pb.update_record.await_args.kwargs["data"]["config"]["_nexa_attempt"] == {
        "attempt_id": "server"
    }


async def test_requeue_clears_old_attempt_and_outputs():
    pb = build_database(config={"_nexa_attempt": {"attempt_id": "old"}, "pages": []})
    await build.update_build("b", BuildUpdateRequest(status="queued"), context(), pb)
    data = pb.update_record.await_args.kwargs["data"]
    assert data["config"] == {"pages": []}
    assert data["image"] == data["started_at"] == data["completed_at"] == ""


@pytest.mark.parametrize("collection", ["properties", "builds"])
async def test_parent_reassignment_during_lock_wait_rejected(collection):
    from app.application.services.record_mutation import locked_record

    pb = AsyncMock()
    pb.find_one_by_filter.side_effect = [
        {"id": "r", "site_id": "before"},
        {"id": "r", "site_id": "after"},
    ]
    with pytest.raises(HTTPException) as exc:
        async with locked_record(
            pb, collection, 'id="r"', "t", build=collection == "builds"
        ):
            pytest.fail("changed parent accepted")
    assert exc.value.status_code == 409
