from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.interface.dependencies import get_pocketbase_client, get_tenant_context
from app.interface.routes import build, site
from app.interface.site_dependencies import get_site_management_client
from tests.unit.test_retained_consumer import context


@pytest.fixture
def boundary_api():
    pb = AsyncMock()
    app = FastAPI()
    app.include_router(build.router, prefix="/builds")
    app.include_router(site.router, prefix="/sites")
    app.dependency_overrides[get_pocketbase_client] = lambda: pb
    app.dependency_overrides[get_site_management_client] = lambda: pb
    app.dependency_overrides[get_tenant_context] = context
    return app, pb


@pytest.mark.parametrize("count,expected", [(200, 200), (201, 422)])
async def test_visible_site_limit_at_http_boundary(boundary_api, count, expected):
    app, pb = boundary_api
    pb.find_one_by_filter.return_value = {"id": "tr"}
    pb.list_records.side_effect = [
        {
            "items": [{"site_id": f"site-{n}"} for n in range(count)],
            "totalItems": count,
        },
        {"items": [], "totalItems": 0},
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/builds")
    assert response.status_code == expected
    assert pb.list_records.await_count == (2 if expected == 200 else 1)
    if expected == 422:
        assert "site_id" in response.json()["detail"]
        assert "total" not in response.json()


@pytest.mark.parametrize("size,expected", [(12000, 200), (12001, 422)])
async def test_filter_byte_limit_at_http_boundary(boundary_api, size, expected):
    app, pb = boundary_api
    ids = [f"site-{n}".ljust(46, "x") for n in range(200)]

    def expression():
        return "(" + " || ".join(f'site_id="{value}"' for value in ids) + ")"

    ids[0] += "x" * (size - len(expression().encode()))
    assert len(expression().encode()) == size
    pb.find_one_by_filter.return_value = {"id": "tr"}
    pb.list_records.side_effect = [
        {"items": [{"site_id": value} for value in ids], "totalItems": 200},
        {"items": [], "totalItems": 0},
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/builds")
    assert response.status_code == expected
    assert pb.list_records.await_count == (2 if expected == 200 else 1)


async def test_site_scope_preserves_pagination_and_totals(boundary_api):
    app, pb = boundary_api
    pb.find_one_by_filter.return_value = {"id": "tr"}
    pb.list_records.side_effect = [
        {"items": [{"site_id": "chosen"}], "totalItems": 1},
        {
            "items": [
                {"id": "b", "build_id": "b", "site_id": "chosen", "status": "failed"}
            ],
            "totalItems": 3,
            "page": 2,
            "perPage": 1,
            "totalPages": 3,
        },
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/builds?site_id=chosen&page=2&per_page=1")
    assert response.status_code == 200
    assert response.json()["total"] == 3 and response.json()["page"] == 2
    parent, builds = [call.kwargs for call in pb.list_records.await_args_list]
    assert 'site_id="chosen"' in parent["filter"]
    assert 'site_id="chosen"' in builds["filter"]
    assert builds["page"] == 2 and builds["per_page"] == 1


@pytest.mark.parametrize("deleted,expected", [(False, 200), (True, 404)])
async def test_config_save_rechecks_current_lifecycle(boundary_api, deleted, expected):
    app, pb = boundary_api
    lifecycle = {"deleted_at": "now"} if deleted else {"cleanup_status": "active"}
    record = {
        "id": "r",
        "site_id": "s",
        "tenant_id": "tr",
        "config": {"_nexa_lifecycle": lifecycle},
    }

    async def find(collection, **kwargs):
        return (
            {"id": "tr", "tenant_id": "tenant"} if collection == "tenants" else record
        )

    pb.find_one_by_filter.side_effect = find
    pb.update_record.side_effect = lambda **kw: {**record, **kw["data"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.patch("/sites/s", json={"config": {"name": "saved"}})
    assert response.status_code == expected
    if deleted:
        pb.update_record.assert_not_awaited()
    else:
        assert response.json()["config"] == {
            "name": "saved",
            "_nexa_lifecycle": lifecycle,
        }


async def test_http_rejects_lifecycle_injection_without_writing(boundary_api):
    app, pb = boundary_api

    async def find(collection, **kwargs):
        if collection == "tenants":
            return {"id": "tr", "tenant_id": "tenant"}
        return {"id": "r", "site_id": "s", "tenant_id": "tr", "config": {}}

    pb.find_one_by_filter.side_effect = find
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/sites/s", json={"config": {"_nexa_lifecycle": {}}}
        )
    assert response.status_code == 422
    pb.update_record.assert_not_awaited()
