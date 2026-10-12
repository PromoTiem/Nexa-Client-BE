from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.access import AuthContext, enforce_site_access
from app.interface.dependencies import TenantContext
from app.interface.dto.site import SiteUpdateRequest
from app.interface.routes import serve, site


def retained():
    return {
        "id": "record",
        "site_id": "s",
        "tenant_id": "tenant_record",
        "config": {"_nexa_lifecycle": {"deleted_at": "2026-10-12"}},
    }


def context():
    return TenantContext(
        auth=AuthContext(
            token="test", record={"id": "user", "tenant_id": "tenant", "role": "owner"}
        ),
        tenant_id="tenant",
    )


async def test_shared_guard_rejects_retained_before_relation_lookup():
    pb = AsyncMock()
    pb.find_one_by_filter.side_effect = [retained(), {"tenant_id": "tenant"}]
    with pytest.raises(HTTPException) as exc:
        await enforce_site_access(pb, "s", context().auth)
    assert exc.value.status_code == 404
    assert pb.find_one_by_filter.await_count == 1


@pytest.mark.parametrize("operation", ["get", "patch", "delete", "serve"])
async def test_direct_site_routes_reject_retained(operation):
    pb = AsyncMock()
    pb.find_one_by_filter.side_effect = [retained(), {"tenant_id": "tenant"}]
    with pytest.raises(HTTPException) as exc:
        if operation == "get":
            await site.get_site("s", context(), pb)
        elif operation == "patch":
            await site.update_site("s", SiteUpdateRequest(config={}), context(), pb)
        elif operation == "delete":
            await site.delete_site("s", context(), pb, AsyncMock(), AsyncMock())
        else:
            await serve._load_site("s", context(), pb)
    assert exc.value.status_code == 404
    pb.update_record.assert_not_awaited()
    pb.delete_record.assert_not_awaited()


async def test_list_queries_active_sites_before_pagination():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"id": "tenant_record"}
    pb.list_records.return_value = {"items": [], "totalItems": 0}
    await site.list_sites(1, 50, "-created_at", None, context(), pb)
    query = pb.list_records.await_args.kwargs
    assert query["collection"] == "sites"
    assert "config._nexa_lifecycle.deleted_at" in query["filter"]
    assert "tenant_record" in query["filter"]


async def test_active_site_still_checks_tenant():
    pb = AsyncMock()
    active = {**retained(), "config": {}}
    pb.find_one_by_filter.side_effect = [active, {"tenant_id": "other"}]
    with pytest.raises(HTTPException) as exc:
        await enforce_site_access(pb, "s", context().auth)
    assert exc.value.status_code == 404


async def test_active_site_allowed():
    pb = AsyncMock()
    active = {**retained(), "config": {}}
    pb.find_one_by_filter.side_effect = [active, {"tenant_id": "tenant"}]
    assert await enforce_site_access(pb, "s", context().auth) == active


@pytest.mark.parametrize("incoming", [{}, None, {"title": "new"}])
def test_config_replacement_preserves_server_metadata(incoming):
    from app.application.access import client_site_config

    existing = {"_nexa_lifecycle": {"cleanup_status": "active"}}
    assert (
        client_site_config(incoming, existing)["_nexa_lifecycle"]
        == existing["_nexa_lifecycle"]
    )


def test_client_cannot_forge_lifecycle():
    from app.application.access import client_site_config

    with pytest.raises(HTTPException) as exc:
        client_site_config({"_nexa_lifecycle": {}})
    assert exc.value.status_code == 422


async def test_retained_bulk_delete_preserves_objects_and_records():
    from app.application.services.storage_service import StorageFileService

    pb, objects = AsyncMock(), AsyncMock()
    pb.find_one_by_filter.side_effect = [
        {
            "id": "file-record",
            "file_id": "f",
            "site_id": "s",
            "bucket": "b",
            "path": "key",
        },
        retained(),
    ]
    service = StorageFileService(objects, 1000)
    assert await service.bulk_delete(["f"], pb, "test", auth=context().auth) == [
        {"file_id": "f", "status": "not_found"}
    ]
    objects.delete_object.assert_not_awaited()
    pb.delete_record.assert_not_awaited()


async def test_retained_public_submission_rejected_before_policy():
    from app.application.services.public_submission_service import create_booking

    pb = AsyncMock()
    pb.find_one_by_filter.return_value = retained()
    with pytest.raises(HTTPException) as exc:
        await create_booking(pb, "s", {})
    assert exc.value.status_code == 404
    assert pb.find_one_by_filter.await_count == 1
    pb.create_record.assert_not_awaited()


async def test_retained_bucket_cannot_be_recreated():
    from app.application.services.bucket_resolver import ensure_site_bucket

    pb, storage = AsyncMock(), AsyncMock()
    pb.find_one_by_filter.return_value = retained()
    with pytest.raises(HTTPException) as exc:
        await ensure_site_bucket("s", pb, storage, "test")
    assert exc.value.status_code == 404
    storage.create_bucket.assert_not_awaited()
    storage.set_bucket_public_policy.assert_not_awaited()


async def test_build_parent_resolution_rejects_retained():
    from app.interface.routes.build import _resolve_site_tenant

    pb = AsyncMock()
    pb.find_one_by_filter.return_value = retained()
    with pytest.raises(HTTPException) as exc:
        await _resolve_site_tenant("s", pb, "test")
    assert exc.value.status_code == 404
