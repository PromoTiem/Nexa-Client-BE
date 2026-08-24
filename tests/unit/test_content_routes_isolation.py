import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException

from app.interface.auth_models import AuthContext
from app.interface.dependencies import TenantContext
from app.interface.routes import (
    template as template_route,
    style as style_route,
    block as block_route,
    page as page_route,
    section as section_route,
)

TENANT_PUBLIC = "tenant_abc"
TENANT_RECORD = "tenant_rec_123"


def _auth(tenant_id: str = TENANT_PUBLIC) -> AuthContext:
    return AuthContext(
        token="tok",
        record={"id": "user_1", "tenant_id": tenant_id, "role": "member"},
    )


def _ctx(tenant_id: str = TENANT_PUBLIC) -> TenantContext:
    return TenantContext(auth=_auth(tenant_id), tenant_id=tenant_id)


BASE_RECORD = {
    "id": "r1",
    "template_id": "tpl",
    "style_id": "sty",
    "block_id": "blk",
    "page_id": "pg",
    "section_id": "sec",
    "name": "n",
}


def _pb(tenant_record_id: str = TENANT_RECORD, content_record=None):
    pb = AsyncMock()
    record = dict(BASE_RECORD)
    if content_record:
        record.update(content_record)

    async def _find_one_by_filter(collection, filter_expr, token=None, expand=None):
        if collection == "tenants":
            return {"id": tenant_record_id}
        return record

    pb.find_one_by_filter = AsyncMock(side_effect=_find_one_by_filter)
    pb.list_records = AsyncMock(
        return_value={
            "items": [record],
            "totalItems": 1,
            "page": 1,
            "perPage": 50,
            "totalPages": 1,
        }
    )
    return pb


# ── Tenant isolation on LIST endpoints ──────────────────────────────── #


class TestListTenantIsolation:
    @pytest.mark.asyncio
    async def test_list_templates_filters_by_tenant(self):
        pb = _pb()
        await template_route.list_templates(
            page=1, per_page=50, sort="-created_at",
            category=None, tags=None, search=None, ctx=_ctx(), pb=pb
        )
        kwargs = pb.list_records.call_args.kwargs
        assert kwargs["collection"] == "templates"
        assert f'tenant_id="{TENANT_RECORD}"' in kwargs["filter"]

    @pytest.mark.asyncio
    async def test_list_styles_filters_by_tenant(self):
        pb = _pb()
        await style_route.list_styles(ctx=_ctx(), pb=pb)
        assert f'tenant_id="{TENANT_RECORD}"' in pb.list_records.call_args.kwargs["filter"]

    @pytest.mark.asyncio
    async def test_list_blocks_filters_by_tenant(self):
        pb = _pb()
        await block_route.list_blocks(ctx=_ctx(), pb=pb)
        assert f'tenant_id="{TENANT_RECORD}"' in pb.list_records.call_args.kwargs["filter"]

    @pytest.mark.asyncio
    async def test_list_pages_filters_by_tenant(self):
        pb = _pb()
        await page_route.list_pages(ctx=_ctx(), pb=pb)
        assert f'tenant_id="{TENANT_RECORD}"' in pb.list_records.call_args.kwargs["filter"]

    @pytest.mark.asyncio
    async def test_list_sections_filters_by_tenant(self):
        pb = _pb()
        await section_route.list_sections(ctx=_ctx(), pb=pb)
        assert f'tenant_id="{TENANT_RECORD}"' in pb.list_records.call_args.kwargs["filter"]


# ── Tenant isolation on GET endpoints ───────────────────────────────── #


class TestGetTenantIsolation:
    @pytest.mark.asyncio
    async def test_get_template_scopes_lookup_by_tenant(self):
        pb = _pb(content_record={"id": "r1", "template_id": "tpl_1"})
        await template_route.get_template(
            template_id="tpl_1", expand=None, ctx=_ctx(), pb=pb
        )
        # The content lookup (collection != tenants) must include the tenant clause.
        content_calls = [
            c for c in pb.find_one_by_filter.call_args_list
            if c.kwargs["collection"] == "templates"
        ]
        assert content_calls
        assert f'tenant_id="{TENANT_RECORD}"' in content_calls[0].kwargs["filter_expr"]

    @pytest.mark.asyncio
    async def test_get_template_cross_tenant_raises_404(self):
        pb = AsyncMock()

        async def _find_one_by_filter(collection, filter_expr, token=None, expand=None):
            if collection == "tenants":
                return {"id": TENANT_RECORD}
            # A record that does not belong to this tenant yields no match.
            raise HTTPException(status_code=404, detail="Record not found")

        pb.find_one_by_filter = AsyncMock(side_effect=_find_one_by_filter)
        with pytest.raises(HTTPException) as exc_info:
            await template_route.get_template(
                template_id="tpl_other", expand=None, ctx=_ctx(), pb=pb
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_block_scopes_lookup_by_tenant(self):
        pb = _pb(content_record={"id": "r1", "block_id": "blk_1"})
        await block_route.get_block(block_id="blk_1", ctx=_ctx(), pb=pb)
        content_calls = [
            c for c in pb.find_one_by_filter.call_args_list
            if c.kwargs["collection"] == "blocks"
        ]
        assert content_calls
        assert f'tenant_id="{TENANT_RECORD}"' in content_calls[0].kwargs["filter_expr"]

    @pytest.mark.asyncio
    async def test_get_page_scopes_lookup_by_tenant(self):
        pb = _pb(content_record={"id": "r1", "page_id": "pg_1"})
        await page_route.get_page(page_id="pg_1", ctx=_ctx(), pb=pb)
        content_calls = [
            c for c in pb.find_one_by_filter.call_args_list
            if c.kwargs["collection"] == "pages"
        ]
        assert content_calls
        assert f'tenant_id="{TENANT_RECORD}"' in content_calls[0].kwargs["filter_expr"]

    @pytest.mark.asyncio
    async def test_get_section_scopes_lookup_by_tenant(self):
        pb = _pb(content_record={"id": "r1", "section_id": "sec_1"})
        await section_route.get_section(section_id="sec_1", ctx=_ctx(), pb=pb)
        content_calls = [
            c for c in pb.find_one_by_filter.call_args_list
            if c.kwargs["collection"] == "sections"
        ]
        assert content_calls
        assert f'tenant_id="{TENANT_RECORD}"' in content_calls[0].kwargs["filter_expr"]


# ── Template expand cross-tenant scoping ────────────────────────────── #


class TestTemplateExpandIsolation:
    @pytest.mark.asyncio
    async def test_expand_style_scoped_by_tenant(self):
        pb = _pb(content_record={"id": "r1", "template_id": "tpl_1", "style_id": "sty_1"})
        await template_route.get_template(
            template_id="tpl_1", expand="style", ctx=_ctx(), pb=pb
        )
        style_calls = [
            c for c in pb.find_one_by_filter.call_args_list
            if c.kwargs["collection"] == "styles"
        ]
        assert style_calls
        assert f'tenant_id="{TENANT_RECORD}"' in style_calls[0].kwargs["filter_expr"]

    @pytest.mark.asyncio
    async def test_expand_pages_scoped_by_tenant(self):
        pb = _pb(
            content_record={
                "id": "r1",
                "template_id": "tpl_1",
                "page_ids": ["pg_1"],
            }
        )
        await template_route.get_template(
            template_id="tpl_1", expand="pages", ctx=_ctx(), pb=pb
        )
        page_calls = [
            c for c in pb.list_records.call_args_list
            if c.kwargs["collection"] == "pages"
        ]
        assert page_calls
        assert f'tenant_id="{TENANT_RECORD}"' in page_calls[0].kwargs["filter"]


# ── Default role behaviour ──────────────────────────────────────────── #


class TestDefaultRole:
    def test_rbac_defaults_missing_role_to_guest(self):
        from app.interface.rbac import has_permission, Permission

        no_role = AuthContext(token="t", record={"id": "u1", "tenant_id": "t1"})
        # Guest can list/read but cannot create users.
        assert has_permission(no_role, Permission.SITES_LIST)
        assert not has_permission(no_role, Permission.USERS_CREATE)

    def test_user_response_defaults_missing_role_to_guest(self):
        from app.interface.routes.user import _record_to_response

        resp = _record_to_response({"id": "u1", "email": "a@b.com"})
        assert resp.role == "guest"


# ── Router wiring: no duplicate /sites prefix ──────────────────────── #


class TestNoDuplicateSitesPrefix:
    def test_no_route_has_duplicated_sites_segment(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert paths, "expected registered paths"
        assert all("/sites/sites" not in p for p in paths), (
            f"Duplicate /sites segment in paths: {paths}"
        )

    def test_property_routes_are_not_double_prefixed(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert any(p == "/sites/{site_id}/properties" for p in paths)
        assert all(
            "/sites/sites/{site_id}/properties" not in p for p in paths
        )
