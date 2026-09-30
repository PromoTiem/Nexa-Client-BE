"""Regressions for the September route/security audit (no external services)."""

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.application.access import AuthContext
from app.application.services.account_service import enforce_account_access
from app.application.services.analytics_service import AnalyticsService
from app.application.services.insight_service import InsightService
from app.application.services.public_submission_service import create_booking
from app.application.services.site_lifecycle_service import (
    create_site_record,
    delete_site_record,
)
from app.config import Settings
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.rate_limits import get_limiter
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_settings,
    get_tenant_context,
)
from app.interface.dto.analytics import (
    AggregateRequest,
    AnalyticsBatchRequest,
    AnalyticsEventRequest,
)
from app.interface.dto.property import PublicBookingRequest
from app.interface.dto.user import UserUpdateRequest
from app.interface.route_helpers import resolve_page_size
from app.interface.routes import (
    analytics,
    auth,
    block,
    build,
    insights,
    section,
    template,
    user,
)


def context(role="admin"):
    return TenantContext(
        AuthContext("token", {"id": "caller", "tenant_id": "tenant-a", "role": role}),
        "tenant-a",
    )


def database(foreign=False):
    pb = AsyncMock()

    async def find(collection, filter_expr, token=None, **kwargs):
        if collection == "sites":
            return {
                "id": "site-record",
                "site_id": "site-a",
                "tenant_id": "tenant-record",
            }
        if collection == "tenants":
            return {
                "id": "tenant-record",
                "tenant_id": "tenant-b" if foreign else "tenant-a",
            }
        return {"id": "property-record", "property_id": "prop-a"}

    pb.find_one_by_filter.side_effect = find
    pb.list_records.return_value = {"items": [], "totalItems": 0}
    return pb


@pytest.mark.parametrize(
    "record",
    [
        {"status": "inactive"},
        {"status": "suspended"},
        {"is_deleted": True},
        {"status": "unknown"},
    ],
)
def test_disabled_account_rejected(record):
    with pytest.raises(HTTPException) as exc:
        enforce_account_access({"tenant_id": "tenant-a", **record})
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", [None])
def test_null_role_rejected_by_dto(role):
    with pytest.raises(ValidationError):
        UserUpdateRequest(role=role)


@pytest.mark.parametrize("operation", ["demote", "disable", "delete"])
async def test_admin_cannot_modify_owner(operation):
    pb = database()
    pb.find_record_by_id.return_value = {
        "id": "owner",
        "tenant_id": "tenant-a",
        "role": "owner",
    }
    with pytest.raises(HTTPException) as exc:
        if operation == "delete":
            await user.delete_user("owner", context(), pb)
        else:
            body = (
                UserUpdateRequest(role="guest")
                if operation == "demote"
                else UserUpdateRequest(status="inactive")
            )
            await user.update_user("owner", body, context(), pb)
    assert exc.value.status_code == 403
    pb.update_record.assert_not_awaited()


async def test_password_recovery_never_looks_up_or_replaces_password():
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    pb = AsyncMock()
    app.dependency_overrides[get_pocketbase_client] = lambda: pb
    app.dependency_overrides[get_settings] = lambda: Settings(
        pocketbase_auth_collection="users"
    )
    auth.limiter.reset()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        known = await client.post(
            "/auth/forgot-password", json={"email": "known@example.com"}
        )
        unknown = await client.post(
            "/auth/forgot-password", json={"email": "unknown@example.com"}
        )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert "password" not in known.json()
    assert "temporary_password" not in known.json()
    assert pb.request_password_reset.await_count == 2
    pb.auth_admin.assert_not_awaited()
    pb.collection_list.assert_not_awaited()
    pb.update_record.assert_not_awaited()


async def test_reset_client_uses_pocketbase_email_endpoint(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(204)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond)),
    )
    await PocketBaseClient("http://pb.test").request_password_reset(
        "users", "user@example.com"
    )
    assert requests[0].url.path == "/api/collections/users/request-password-reset"
    assert requests[0].read() == b'{"email":"user@example.com"}'
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize("batch", [False, True])
async def test_foreign_tracking_never_buffers(batch):
    pb, collector = database(foreign=True), AsyncMock()
    event = AnalyticsEventRequest(site_id="site-b", event_type="page_view")
    with pytest.raises(HTTPException) as exc:
        if batch:
            await analytics.track_events_batch(
                AnalyticsBatchRequest(events=[event]), context(), pb, collector
            )
        else:
            await analytics.track_event(event, context(), pb, collector)
    assert exc.value.status_code == 404
    collector.record_event.assert_not_awaited()


@pytest.mark.parametrize(
    "operation", ["dashboard", "trends", "top", "product", "aggregate"]
)
async def test_foreign_analytics_cannot_read_or_aggregate(operation):
    pb, collector = database(foreign=True), AsyncMock()
    calls = {
        "dashboard": lambda: analytics.get_dashboard(
            "site-b", "30d", None, context(), pb, collector
        ),
        "trends": lambda: analytics.get_trends(
            "site-b", "30d", "views_trend", "daily", None, context(), pb, collector
        ),
        "top": lambda: analytics.get_top_products(
            "site-b", "30d", "views", 10, None, context(), pb, collector
        ),
        "product": lambda: analytics.get_product_analytics(
            "site-b", "prop", "30d", context(), pb, collector
        ),
        "aggregate": lambda: analytics.aggregate_analytics(
            "site-b",
            AggregateRequest(start_date="2026-01-01", end_date="2026-01-01"),
            context(),
            pb,
            collector,
        ),
    }
    with pytest.raises(HTTPException) as exc:
        await calls[operation]()
    assert exc.value.status_code == 404
    pb.list_records.assert_not_awaited()
    pb.create_record.assert_not_awaited()


@pytest.mark.parametrize(
    "operation", ["analyze", "batch", "score", "seo", "recommendations", "summary"]
)
async def test_foreign_insights_never_reach_llm(operation):
    from app.interface.dto.insights import BatchAnalysisRequest

    service = InsightService(database(foreign=True), AsyncMock())
    calls = {
        "analyze": lambda: insights.analyze_property(
            "site-b", "prop", None, context(), service
        ),
        "batch": lambda: insights.batch_analyze(
            "site-b", BatchAnalysisRequest(), context(), service
        ),
        "score": lambda: insights.get_score("site-b", "prop", context(), service),
        "seo": lambda: insights.get_seo("site-b", "prop", context(), service),
        "recommendations": lambda: insights.get_recommendations(
            "site-b", "all", None, 50, context(), service
        ),
        "summary": lambda: insights.get_site_summary("site-b", context(), service),
    }
    with pytest.raises(HTTPException) as exc:
        await calls[operation]()
    assert exc.value.status_code == 404
    assert service._llm.mock_calls == []
    service._pb.list_records.assert_not_awaited()


async def test_build_filter_escapes_or_payload():
    pb = database()
    await build.list_builds(
        page=1,
        per_page=50,
        sort="-created_at",
        site_id=None,
        status='queued" || status!="',
        ctx=context(),
        pb=pb,
    )
    expression = pb.list_records.call_args.kwargs["filter"]
    assert 'status="queued\\" || status!=\\""' in expression
    assert 'tenant_id="tenant-record"' in expression


@pytest.mark.parametrize(
    "start,end",
    [("bad", "2026-01-01"), ("2026-02-01", "2026-01-01"), ("2020-01-01", "2026-01-01")],
)
def test_bad_aggregate_dates_rejected(start, end):
    with pytest.raises(ValidationError):
        AggregateRequest(start_date=start, end_date=end)


@pytest.mark.parametrize(
    "period,expected",
    [
        (
            "daily",
            [{"date": "2026-01-01", "value": 2}, {"date": "2026-01-02", "value": 3}],
        ),
        ("weekly", [{"date": "2025-12-29", "value": 5}]),
        ("monthly", [{"date": "2026-01-01", "value": 5}]),
    ],
)
async def test_trend_period_buckets(period, expected):
    service = AnalyticsService(AsyncMock(), AsyncMock(), AsyncMock())
    service._query_aggregates = AsyncMock(
        return_value=[
            {"date": "2026-01-01", "total_views": 2},
            {"date": "2026-01-02", "total_views": 3},
        ]
    )
    assert (
        await service.get_trend(
            "site", "views_trend", "2026-01-01", "2026-01-02", period=period
        )
        == expected
    )


async def test_top_type_filter_precedes_limit():
    pb = AsyncMock()
    pb.list_records.return_value = {
        "items": [{"property_id": "small", "type": "spa_service", "name": "Small"}]
    }
    service = AnalyticsService(AsyncMock(), AsyncMock(), pb)
    service._query_aggregates = AsyncMock(
        return_value=[
            {"property_id": "large", "total_views": 100},
            {
                "property_id": "small",
                "total_views": 10,
                "unique_visitors": 5,
                "purchases": 2,
            },
        ]
    )
    result = await service.get_top_properties(
        "site",
        "views",
        "2026-01-01",
        "2026-01-02",
        limit=1,
        property_type="spa_service",
    )
    assert result[0]["property_id"] == "small"
    assert result[0]["unique_visitors"] == 5
    assert result[0]["conversion_rate"] == 20
    assert 'type="spa_service"' in pb.list_records.call_args.kwargs["filter"]


async def test_batch_paginates_and_filters():
    pb = AsyncMock()
    pb.list_records.side_effect = [
        {"items": [{"property_id": str(i)} for i in range(500)], "totalPages": 2},
        {"items": [{"property_id": "last"}], "totalPages": 2},
    ]
    result = await InsightService(pb, AsyncMock()).list_batch_properties(
        "site", "spa_service"
    )
    assert len(result) == 501
    for call in pb.list_records.call_args_list:
        assert 'deleted_at=""' in call.kwargs["filter"]
        assert 'type="spa_service"' in call.kwargs["filter"]


@pytest.mark.parametrize("extra", [{"type": "post"}, {"seo": {}}])
def test_public_dto_rejects_authoring_fields(extra):
    with pytest.raises(ValidationError):
        PublicBookingRequest(
            name="Customer", fields=[], metadata={"service_id": "svc"}, **extra
        )


async def test_public_submission_requires_site_opt_in():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"config": {}}
    with pytest.raises(HTTPException) as exc:
        await create_booking(pb, "site", {})
    assert exc.value.status_code == 404
    pb.create_record.assert_not_awaited()


async def test_public_submission_uses_server_schema():
    pb = AsyncMock()
    pb.find_one_by_filter.side_effect = [
        {
            "config": {
                "public_submissions": {"enabled": True, "types": ["booking_submission"]}
            }
        },
        {
            "groups": [
                {
                    "key": "booking",
                    "fields": [
                        {
                            "key": "phone",
                            "label": "Phone",
                            "type": "text",
                            "required": True,
                        }
                    ],
                }
            ]
        },
    ]
    with pytest.raises(HTTPException) as exc:
        await create_booking(
            pb,
            "site",
            {
                "name": "Customer",
                "fields": [{"key": "phone", "value": None, "required": False}],
                "metadata": {"service_id": "svc"},
            },
        )
    assert exc.value.status_code == 400
    pb.create_record.assert_not_awaited()


async def test_site_duplicate_create_does_not_delete_existing_bucket():
    pb, storage = AsyncMock(), AsyncMock()
    storage.bucket_exists.return_value = True
    with pytest.raises(HTTPException) as exc:
        await create_site_record(
            pb, storage, {"site_id": "existing-site"}, "token", "user", "example.com"
        )
    assert exc.value.status_code == 409
    storage.delete_bucket.assert_not_awaited()
    pb.create_record.assert_not_awaited()


async def test_site_cleanup_failure_preserves_retry_record(monkeypatch):
    import app.application.services.site_lifecycle_service as lifecycle

    monkeypatch.setattr(lifecycle, "remove_domain_from_pages", AsyncMock())
    monkeypatch.setattr(lifecycle, "remove_dns_for_domain", AsyncMock())
    pb, storage = AsyncMock(), AsyncMock()
    pb.list_records.return_value = {"items": []}
    storage.empty_bucket.side_effect = HTTPException(502, "storage unavailable")
    with pytest.raises(HTTPException):
        await delete_site_record(
            pb,
            AsyncMock(),
            storage,
            {"id": "record", "site_id": "site", "bucket_name": "custom-bucket"},
            "token",
            "example.com",
        )
    storage.empty_bucket.assert_awaited_once_with("custom-bucket")
    pb.delete_record.assert_not_awaited()


async def test_shared_bucket_never_deleted():
    pb, storage, cf = AsyncMock(), AsyncMock(), AsyncMock()
    pb.list_records.return_value = {"items": [{"id": "other-site"}]}
    with pytest.raises(HTTPException) as exc:
        await delete_site_record(
            pb, cf, storage, {"id": "record", "site_id": "site"}, "token", "example.com"
        )
    assert exc.value.status_code == 409
    assert storage.mock_calls == []
    assert cf.mock_calls == []


def test_zero_and_false_survive_mapping():
    assert (
        block._record_to_response(
            {"id": "r", "block_id": "b", "order_index": 0}
        ).order_index
        == 0
    )
    assert (
        section._record_to_response(
            {"id": "r", "section_id": "s", "order_index": 0}
        ).order_index
        == 0
    )
    assert (
        template._record_to_response(
            {"id": "r", "template_id": "t", "is_valid": False}
        ).is_valid
        is False
    )


def test_page_size_alias_conflict():
    assert resolve_page_size(None, 42) == 42
    assert resolve_page_size(42, None) == 42
    with pytest.raises(HTTPException) as exc:
        resolve_page_size(20, 42)
    assert exc.value.status_code == 422


async def test_tenant_rate_limit_isolated_and_returns_retry_header():
    from fastapi import Depends

    from app.interface.exception_handlers import register_exception_handlers
    from app.interface.rate_limits import tenant_limit

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/limited", dependencies=[Depends(tenant_limit("regression", "1/minute"))])
    async def limited():
        return {"ok": True}

    app.dependency_overrides[get_settings] = lambda: Settings(
        rate_limit_storage_uri="memory://"
    )
    app.dependency_overrides[get_tenant_context] = lambda: context()
    get_limiter("memory://").storage.reset()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/limited")).status_code == 200
        denied = await client.get("/limited")
        assert denied.status_code == 429
        assert denied.headers["retry-after"] == "60"
        second = context()
        second.tenant_id = "tenant-b"
        app.dependency_overrides[get_tenant_context] = lambda: second
        assert (await client.get("/limited")).status_code == 200


def test_application_and_infrastructure_do_not_import_interface():
    for root in (Path("app/application"), Path("app/infrastructure")):
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith("app.interface"), path
                elif isinstance(node, ast.Import):
                    assert all(
                        not item.name.startswith("app.interface") for item in node.names
                    ), path


def test_openapi_retains_routes_and_valid_path_parameters():
    import re

    from app.interface.routes import router

    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]
    assert sum(len(methods) for methods in paths.values()) == 72
    for path, methods in paths.items():
        path_names = set(re.findall(r"\{([^}]+)\}", path))
        assert all(name.isidentifier() for name in path_names)
        for operation in methods.values():
            declared = {
                p["name"] for p in operation.get("parameters", []) if p["in"] == "path"
            }
            assert declared == path_names
    assert "/analytics/dashboard/{site_id}" in paths
    assert "/analytics/product/{site_id}/{property_id}" in paths


async def test_analytics_dashboard_http_path_enforces_ownership():
    from app.interface.dependencies import get_analytics_collector

    app = FastAPI()
    app.include_router(analytics.router)
    pb = database(foreign=True)
    app.dependency_overrides[get_pocketbase_client] = lambda: pb
    app.dependency_overrides[get_tenant_context] = lambda: context()
    app.dependency_overrides[get_analytics_collector] = lambda: AsyncMock()
    app.dependency_overrides[get_settings] = lambda: Settings(
        rate_limit_storage_uri="memory://"
    )
    get_limiter("memory://").storage.reset()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/analytics/dashboard/site-b")
    assert response.status_code == 404
    pb.list_records.assert_not_awaited()


async def test_public_body_limit_rejects_chunked_oversize_before_handler():
    from app.interface.middlewares.public_body_limit import PublicBodyLimitMiddleware

    app = FastAPI()
    app.add_middleware(PublicBodyLimitMiddleware, max_bytes=10)
    called = False

    @app.post("/public/test")
    async def handler():
        nonlocal called
        called = True
        return {}

    async def chunks():
        yield b"123456"
        yield b"789012"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/public/test", content=chunks())
    assert response.status_code == 413
    assert not called


async def test_kpi_changes_use_same_property():
    service = AnalyticsService(AsyncMock(), AsyncMock(), AsyncMock())
    service.get_kpis = AsyncMock(side_effect=[{"total_views": 20}, {"total_views": 10}])
    result = await service.get_kpis_change("site", "30d", property_id="prop")
    assert result["total_views"] == 100
    assert all(
        call.kwargs["property_id"] == "prop" for call in service.get_kpis.call_args_list
    )


async def test_site_create_pb_failure_never_removes_storage():
    pb, storage = AsyncMock(), AsyncMock()
    storage.bucket_exists.return_value = False
    pb.list_records.return_value = {"items": []}
    pb.create_record.side_effect = HTTPException(400, "duplicate")
    with pytest.raises(HTTPException):
        await create_site_record(
            pb, storage, {"site_id": "test-site"}, "token", "user", "example.com"
        )
    storage.create_bucket.assert_not_awaited()
    storage.delete_bucket.assert_not_awaited()


async def test_site_create_configures_browser_cors():
    pb, storage = AsyncMock(), AsyncMock()
    storage.bucket_exists.return_value = False
    pb.list_records.return_value = {"items": []}
    pb.create_record.return_value = {"id": "record"}
    await create_site_record(
        pb, storage, {"site_id": "test-site"}, "token", "user", "example.com"
    )
    storage.set_bucket_cors.assert_awaited_once_with(
        "test-site", ["https://example.com", "https://*.example.com"]
    )


async def test_public_booking_persists_only_published_and_trusted_fields():
    pb = AsyncMock()
    pb.find_one_by_filter.side_effect = [
        {
            "config": {
                "public_submissions": {"enabled": True, "types": ["booking_submission"]}
            }
        },
        {
            "groups": [
                {
                    "key": "booking",
                    "fields": [
                        {
                            "key": "phone",
                            "label": "Phone",
                            "type": "text",
                            "required": True,
                        }
                    ],
                }
            ]
        },
    ]
    await create_booking(
        pb,
        "site",
        {
            "name": "Customer",
            "fields": [{"key": "phone", "value": "123", "type": "richtext"}],
            "metadata": {"service_id": "svc"},
        },
    )
    data = pb.create_record.call_args.kwargs["data"]
    assert data["status"] == "published"
    assert data["type"] == "booking_submission"
    assert data["fields"][0]["type"] == "text"
    assert data["property_id"].startswith("booking_")


@pytest.mark.parametrize("model,field", [(UserUpdateRequest, "status")])
def test_required_patch_field_rejects_null(model, field):
    with pytest.raises(ValidationError):
        model(**{field: None})
