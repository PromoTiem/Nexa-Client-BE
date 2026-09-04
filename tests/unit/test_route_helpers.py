from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.interface.auth_models import AuthContext
from app.interface.route_helpers import (
    auth_tenant,
    build_filter,
    ensure_file_tenant,
    ensure_site_tenant,
    ensure_tenant_owns,
    public_id_to_record_id,
    record_id_to_public_id,
    validate_id,
)


class TestValidateId:
    def test_valid_id_passes(self):
        validate_id("my_site_123", "site_id")
        validate_id("test-abc", "id")
        validate_id("ABC123", "id")

    def test_invalid_id_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_id("bad id!", "site_id")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            validate_id("has/slash", "id")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            validate_id("", "id")
        assert exc_info.value.status_code == 400


class TestBuildFilter:
    def test_joins_parts_with_and(self):
        result = build_filter(['a="1"', 'b="2"'])
        assert result == 'a="1" && b="2"'

    def test_single_part_returns_as_is(self):
        result = build_filter(['a="1"'])
        assert result == 'a="1"'

    def test_empty_list_returns_none(self):
        assert build_filter([]) is None


class TestAuthTenant:
    def test_returns_tenant_id(self):
        auth = AuthContext(token="tok", record={"tenant_id": "tenant_123"})
        assert auth_tenant(auth) == "tenant_123"

    def test_returns_none_if_missing(self):
        auth = AuthContext(token="tok", record={"email": "a@b.com"})
        assert auth_tenant(auth) is None


class TestEnsureTenantOwns:
    def test_matching_tenant_passes(self):
        auth = AuthContext(token="tok", record={"tenant_id": "t1"})
        record = {"id": "rec1", "tenant_id": "t1"}
        ensure_tenant_owns(record, auth)

    def test_non_matching_tenant_raises_404(self):
        auth = AuthContext(token="tok", record={"tenant_id": "t1"})
        record = {"id": "rec1", "tenant_id": "t2"}

        with pytest.raises(HTTPException) as exc_info:
            ensure_tenant_owns(record, auth)
        assert exc_info.value.status_code == 404

    def test_no_tenant_on_auth_passes(self):
        auth = AuthContext(token="tok", record={"email": "a@b.com"})
        record = {"id": "rec1", "tenant_id": "t2"}
        ensure_tenant_owns(record, auth)


class TestEnsureSiteTenant:
    @pytest.mark.asyncio
    async def test_no_tenant_on_auth_passes(self):
        pb = AsyncMock()
        auth = AuthContext(token="tok", record={"email": "a@b.com"})
        await ensure_site_tenant(pb, "site_1", auth)
        pb.find_one_by_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_site_belongs_to_tenant_passes(self):
        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            return_value={"id": "pb_t1", "tenant_id": "pb_t1"}
        )
        auth = AuthContext(token="tok", record={"tenant_id": "tenant_abc"})

        async def mock_record_to_public(*args, **kwargs):
            return "tenant_abc"

        import app.interface.route_helpers as rh

        original = rh.record_id_to_public_id
        rh.record_id_to_public_id = mock_record_to_public
        try:
            await ensure_site_tenant(pb, "site_1", auth)
        finally:
            rh.record_id_to_public_id = original

    @pytest.mark.asyncio
    async def test_site_belongs_to_different_tenant_raises_404(self):
        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            return_value={"id": "pb_t1", "tenant_id": "pb_t_other"}
        )
        auth = AuthContext(token="tok", record={"tenant_id": "tenant_abc"})

        async def mock_record_to_public(*args, **kwargs):
            return "tenant_xyz"

        import app.interface.route_helpers as rh

        original = rh.record_id_to_public_id
        rh.record_id_to_public_id = mock_record_to_public
        try:
            with pytest.raises(HTTPException) as exc_info:
                await ensure_site_tenant(pb, "site_1", auth)
            assert exc_info.value.status_code == 404
        finally:
            rh.record_id_to_public_id = original


class TestEnsureFileTenant:
    @pytest.mark.asyncio
    async def test_no_tenant_on_auth_passes(self):
        pb = AsyncMock()
        auth = AuthContext(token="tok", record={"email": "a@b.com"})
        record = {"site_id": "site_1"}
        await ensure_file_tenant(pb, record, auth)

    @pytest.mark.asyncio
    async def test_no_site_id_passes(self):
        pb = AsyncMock()
        auth = AuthContext(token="tok", record={"tenant_id": "t1"})
        record = {"name": "file_1"}
        await ensure_file_tenant(pb, record, auth)

    @pytest.mark.asyncio
    async def test_site_belongs_to_tenant_passes(self):
        pb = AsyncMock()
        auth = AuthContext(token="tok", record={"tenant_id": "t1"})
        record = {"site_id": "site_1"}

        import app.interface.route_helpers as rh

        original = rh.ensure_site_tenant
        rh.ensure_site_tenant = AsyncMock()
        try:
            await ensure_file_tenant(pb, record, auth)
        finally:
            rh.ensure_site_tenant = original


class TestPublicIdToRecordId:
    @pytest.mark.asyncio
    async def test_returns_record_id(self):
        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(return_value={"id": "pb_rec_123"})

        result = await public_id_to_record_id(
            pb, "tenants", "tenant_id", "tenant_abc", "token"
        )
        assert result == "pb_rec_123"


class TestRecordIdToPublicId:
    @pytest.mark.asyncio
    async def test_returns_public_id(self):
        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            return_value={"id": "pb_rec_123", "tenant_id": "tenant_abc"}
        )

        result = await record_id_to_public_id(
            pb, "tenants", "tenant_id", "pb_rec_123", "token"
        )
        assert result == "tenant_abc"

    @pytest.mark.asyncio
    async def test_none_record_id_returns_none(self):
        pb = AsyncMock()
        result = await record_id_to_public_id(pb, "tenants", "tenant_id", None, "token")
        assert result is None

    @pytest.mark.asyncio
    async def test_http_exception_returns_none(self):
        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Not found")
        )

        result = await record_id_to_public_id(
            pb, "tenants", "tenant_id", "pb_rec_123", "token"
        )
        assert result is None
