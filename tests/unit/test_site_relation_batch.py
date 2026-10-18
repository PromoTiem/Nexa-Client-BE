from unittest.mock import AsyncMock

from app.interface.route_helpers import map_site_records


async def test_relations_batched_deduplicated_without_mutating_rows():
    pb = AsyncMock()
    pb.list_records.side_effect = [
        {"items": [{"id": "t", "tenant_id": "tenant"}]},
        {"items": [{"id": "p", "template_id": "template"}]},
        {"items": []},
    ]
    rows = [
        {"tenant_id": "t", "template_id": "p", "domain_id": "missing"}
        for _ in range(20)
    ]
    mapped = await map_site_records(rows, "tenant-token", pb)
    assert pb.list_records.await_count == 3
    assert (
        mapped
        == [{"tenant_id": "tenant", "template_id": "template", "domain_id": None}] * 20
    )
    assert rows[0]["tenant_id"] == "t"
    for call in pb.list_records.await_args_list:
        assert call.kwargs["token"] == "tenant-token"
        assert call.kwargs["per_page"] == 1


async def test_empty_page_makes_no_requests():
    pb = AsyncMock()
    assert await map_site_records([], "t", pb) == []
    pb.list_records.assert_not_awaited()


async def test_relation_requests_are_bounded():
    pb = AsyncMock()
    pb.list_records.return_value = {"items": []}
    await map_site_records([{"tenant_id": str(i)} for i in range(101)], "t", pb)
    assert [c.kwargs["per_page"] for c in pb.list_records.await_args_list] == [100, 1]


async def test_relation_failure_propagates():
    import pytest
    from fastapi import HTTPException

    pb = AsyncMock()
    pb.list_records.side_effect = HTTPException(status_code=403, detail="denied")
    with pytest.raises(HTTPException) as error:
        await map_site_records([{"tenant_id": "t"}], "caller", pb)
    assert error.value.status_code == 403


async def test_site_pages_keep_scope_pagination_and_constant_relation_queries():
    from app.interface.auth_models import AuthContext
    from app.interface.dependencies import TenantContext
    from app.interface.routes.site import ACTIVE_SITE_FILTER, list_sites

    ctx = TenantContext(
        auth=AuthContext(token="caller", record={"id": "user", "role": "owner"}),
        tenant_id="tenant",
    )
    for size in (1, 20, 100):
        pb = AsyncMock()
        pb.find_one_by_filter.return_value = {"id": "t"}
        rows = [
            {
                "id": str(i),
                "site_id": f"site-{i}",
                "tenant_id": "t",
                "template_id": "p",
                "domain_id": "d",
            }
            for i in range(size)
        ]
        pb.list_records.side_effect = [
            {
                "items": rows,
                "totalItems": 300,
                "page": 2,
                "perPage": size,
                "totalPages": 300 // size,
            },
            {"items": [{"id": "t", "tenant_id": "tenant"}]},
            {"items": [{"id": "p", "template_id": "template"}]},
            {"items": [{"id": "d", "domain_id": "domain"}]},
        ]
        result = await list_sites(2, size, "-created_at", "another-tenant", ctx, pb)
        calls = pb.list_records.await_args_list
        assert len(calls) == 4
        assert calls[0].kwargs == {
            "collection": "sites",
            "token": "caller",
            "filter": f'tenant_id="t" && {ACTIVE_SITE_FILTER}',
            "sort": "-created_at",
            "page": 2,
            "per_page": size,
        }
        assert all(call.kwargs["token"] == "caller" for call in calls)
        assert result.total == 300 and result.page == 2 and result.per_page == size
        assert result.total_pages == 300 // size
        assert [item.site_id for item in result.items] == [
            f"site-{i}" for i in range(size)
        ]
        assert all(
            item.tenant_id == "tenant"
            and item.template_id == "template"
            and item.domain_id == "domain"
            for item in result.items
        )
        assert rows[0]["tenant_id"] == "t"
