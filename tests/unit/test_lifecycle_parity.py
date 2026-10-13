from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.interface.routes import build, site
from tests.unit.test_retained_consumer import context


async def test_build_list_filters_parent_before_pagination():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"id": "tenant-record"}
    pb.list_records.side_effect = [
        {"items": [{"site_id": "active"}], "totalItems": 1},
        {"items": [], "totalItems": 0, "page": 2, "perPage": 5, "totalPages": 0},
    ]
    result = await build.list_builds(2, 5, "-created_at", None, None, context(), pb)
    parent_query, query = [call.kwargs for call in pb.list_records.await_args_list]
    assert "config._nexa_lifecycle.deleted_at" in parent_query["filter"]
    assert 'tenant_id="tenant-record"' in parent_query["filter"]
    assert 'site_id="active"' in query["filter"]
    assert "@collection" not in query["filter"]
    assert query["page"] == 2 and query["per_page"] == 5
    assert result.total == 0


async def test_build_list_requires_tenant():
    pb = AsyncMock()
    ctx = context()
    ctx.tenant_id = None
    with pytest.raises(HTTPException) as exc:
        await build.list_builds(1, 5, "-created_at", None, None, ctx, pb)
    assert exc.value.status_code == 403
    pb.list_records.assert_not_awaited()


async def test_delete_retains_records_without_external_cleanup():
    pb, cf, storage = AsyncMock(), AsyncMock(), AsyncMock()
    record = {
        "id": "r",
        "site_id": "s",
        "tenant_id": "tr",
        "config": {"name": "kept"},
        "bucket_name": "b",
    }
    pb.find_one_by_filter.side_effect = [record, {"tenant_id": "tenant"}]
    pb.find_record_by_id.return_value = record
    pb.list_records.return_value = {"items": []}
    # Route must no longer depend on external clients for normal deletion.
    await site.delete_site("s", context(), pb)
    pb.delete_record.assert_not_awaited()
    assert not cf.mock_calls and not storage.mock_calls
    config = pb.update_record.await_args.kwargs["data"]["config"]
    assert config["name"] == "kept"
    assert config["_nexa_lifecycle"]["resource_policy"] == "retain"
    assert config["_nexa_lifecycle"]["deleted_by"] == "user"


@pytest.mark.parametrize("status", ["queued", "building"])
async def test_active_build_blocks_retention(status):
    from app.application.services.site_lifecycle_service import delete_site_record

    pb = AsyncMock()
    record = {"id": "r", "site_id": "s", "config": {}}
    pb.find_record_by_id.return_value = record
    pb.list_records.return_value = {"items": [{"status": status}]}
    with pytest.raises(HTTPException) as exc:
        await delete_site_record(pb, record, "test", "user")
    assert exc.value.status_code == 409
    pb.update_record.assert_not_awaited()


async def test_retention_retry_does_not_change_timestamp():
    from app.application.services.site_lifecycle_service import delete_site_record

    pb = AsyncMock()
    record = {
        "id": "r",
        "site_id": "s",
        "config": {"_nexa_lifecycle": {"deleted_at": "earlier"}},
    }
    pb.find_record_by_id.return_value = record
    await delete_site_record(pb, record, "test")
    pb.update_record.assert_not_awaited()


@pytest.mark.parametrize("operation", ["confirm", "delete", "metadata"])
async def test_waiting_file_mutation_rechecks_retained_parent(operation):
    import asyncio

    from app.application.services.storage_service import StorageFileService
    from app.infrastructure.operation_lock import operation_lock

    pb, storage = AsyncMock(), AsyncMock()
    file = {
        "id": "f",
        "file_id": "f",
        "site_id": "parity-race",
        "bucket": "b",
        "path": "p",
    }
    parent = {"config": {}}
    read = asyncio.Event()

    async def find(collection, **kwargs):
        if collection == "sites":
            return parent
        read.set()
        return file

    pb.find_one_by_filter.side_effect = find
    service = StorageFileService(storage, 1000)
    async with operation_lock("site:parity-race"):
        if operation == "confirm":
            task = asyncio.create_task(service.confirm_upload("f", pb, "t", "u"))
        elif operation == "metadata":
            task = asyncio.create_task(service.update_metadata("f", {}, pb, "t", "u"))
        else:
            task = asyncio.create_task(service.delete_file("f", pb, "t"))
        await asyncio.wait_for(read.wait(), 1)
        assert not task.done()
        parent["config"] = {"_nexa_lifecycle": {"deleted_at": "now"}}
    with pytest.raises(HTTPException) as exc:
        await asyncio.wait_for(task, 1)
    assert exc.value.status_code == 404
    assert not storage.mock_calls
    pb.update_record.assert_not_awaited()
    pb.delete_record.assert_not_awaited()


@pytest.mark.parametrize("operation", ["config", "build", "serve"])
async def test_waiting_route_rechecks_retention(operation):
    import asyncio

    from app.infrastructure.operation_lock import operation_lock
    from app.interface.dto.build import BuildCreateRequest
    from app.interface.dto.serve import ServeStatusPatchRequest
    from app.interface.dto.site import SiteUpdateRequest
    from app.interface.routes import serve

    pb = AsyncMock()
    parent = {"id": "r", "site_id": "route-race", "tenant_id": "tr", "config": {}}

    async def find(collection, **kwargs):
        return (
            {"id": "tr", "tenant_id": "tenant"} if collection == "tenants" else parent
        )

    pb.find_one_by_filter.side_effect = find
    started = asyncio.Event()

    async def request():
        started.set()
        if operation == "config":
            return await site.update_site(
                "route-race", SiteUpdateRequest(config={}), context(), pb
            )
        if operation == "build":
            return await build.create_build(
                BuildCreateRequest(build_id="b", site_id="route-race"), context(), pb
            )
        return await serve.patch_serve_status(
            "route-race", ServeStatusPatchRequest(status="requested"), context(), pb
        )

    async with operation_lock("site:route-race"):
        task = asyncio.create_task(request())
        await asyncio.wait_for(started.wait(), 2)
        assert not task.done()
        parent["config"] = {"_nexa_lifecycle": {"deleted_at": "now"}}
    with pytest.raises(HTTPException) as exc:
        await asyncio.wait_for(task, 2)
    assert exc.value.status_code == 404
    pb.update_record.assert_not_awaited()
    pb.create_record.assert_not_awaited()


async def test_domain_already_owned_is_not_reassigned():
    from app.interface.dto.site import SiteUpdateRequest

    pb = AsyncMock()

    async def find(collection, **kwargs):
        if collection == "sites":
            return {"id": "r", "site_id": "s", "tenant_id": "tr"}
        if collection == "tenants":
            return {"id": "tr", "tenant_id": "tenant"}
        return {"id": "domain-record", "tenant_id": "tr"}

    pb.find_one_by_filter.side_effect = find
    pb.list_records.return_value = {"items": [{"id": "other"}]}
    with pytest.raises(HTTPException) as exc:
        await site.update_site("s", SiteUpdateRequest(domain_id="d"), context(), pb)
    assert exc.value.status_code == 409
    pb.update_record.assert_not_awaited()


async def test_large_tenant_requires_site_scope_without_partial_total():
    from app.application.services.build_visibility import visible_site_filter

    pb = AsyncMock()
    pb.list_records.return_value = {"items": [], "totalItems": 201}
    with pytest.raises(HTTPException) as exc:
        await visible_site_filter(pb, "t", "tenant", None)
    assert exc.value.status_code == 422


async def test_no_active_parent_returns_empty_without_reading_builds():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"id": "tr"}
    pb.list_records.return_value = {"items": [], "totalItems": 0}
    result = await build.list_builds(
        1, 5, "-created_at", "retained", None, context(), pb
    )
    assert result.total == 0 and result.items == []
    assert pb.list_records.await_count == 1
    assert pb.list_records.await_args.kwargs["collection"] == "sites"


async def test_site_lock_coordinates_independent_processes():
    import asyncio
    import sys
    import uuid

    from app.infrastructure.operation_lock import operation_lock

    name = f"test-parity:{uuid.uuid4().hex}"
    code = """import asyncio, sys
from app.infrastructure.operation_lock import operation_lock
async def run():
    print("ready", flush=True)
    async with operation_lock(sys.argv[1]):
        print("acquired", flush=True)
asyncio.run(run())
"""
    child = None
    try:
        async with operation_lock(name):
            child = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code, name, stdout=asyncio.subprocess.PIPE
            )
            assert await asyncio.wait_for(child.stdout.readline(), 5) == b"ready\n"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(child.stdout.readline(), 0.15)
        assert await asyncio.wait_for(child.stdout.readline(), 5) == b"acquired\n"
        assert await asyncio.wait_for(child.wait(), 5) == 0
    finally:
        if child and child.returncode is None:
            child.terminate()
            await child.wait()
