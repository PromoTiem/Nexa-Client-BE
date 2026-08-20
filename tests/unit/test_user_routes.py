import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException

from app.interface.auth_models import AuthContext
from app.interface.dependencies import SuperAdminContext, TenantContext
from app.interface.rbac import require_permission, Permission, has_permission
from app.interface.routes.user import (
    _record_to_response,
    get_my_profile,
    update_my_profile,
    list_users,
    create_user,
    get_user,
    update_user,
    delete_user,
)


MOCK_ADMIN_AUTH = AuthContext(
    token="admin_token",
    record={
        "id": "user_admin",
        "email": "admin@example.com",
        "tenant_id": "tenant_abc",
        "role": "admin",
    },
)

MOCK_OWNER_AUTH = AuthContext(
    token="owner_token",
    record={
        "id": "user_owner",
        "email": "owner@example.com",
        "tenant_id": "tenant_abc",
        "role": "owner",
    },
)

MOCK_MEMBER_AUTH = AuthContext(
    token="member_token",
    record={
        "id": "user_member",
        "email": "member@example.com",
        "tenant_id": "tenant_abc",
        "role": "member",
    },
)

MOCK_USER_RECORD = {
    "id": "user_123",
    "email": "test@example.com",
    "name": "Test User",
    "avatar": "",
    "phone": "1234567890",
    "tenant_id": "tenant_abc",
    "role": "member",
    "status": "active",
    "last_login": "",
    "metadata": {},
    "created": "2026-01-01 00:00:00.000Z",
    "updated": "2026-01-01 00:00:00.000Z",
}


def _tenant_ctx(auth: AuthContext) -> TenantContext:
    return TenantContext(auth=auth, tenant_id=auth.record.get("tenant_id"))


class TestRequireAdminRole:
    def test_admin_has_users_permission(self):
        assert has_permission(MOCK_ADMIN_AUTH, Permission.USERS_LIST)

    def test_owner_has_users_permission(self):
        assert has_permission(MOCK_OWNER_AUTH, Permission.USERS_LIST)

    def test_member_lacks_users_permission(self):
        assert not has_permission(MOCK_MEMBER_AUTH, Permission.USERS_LIST)


class TestRecordToResponse:
    def test_maps_record_fields(self):
        result = _record_to_response(MOCK_USER_RECORD)
        assert result.id == "user_123"
        assert result.email == "test@example.com"
        assert result.name == "Test User"
        assert result.tenant_id == "tenant_abc"
        assert result.role == "member"
        assert result.status == "active"

    def test_handles_missing_optional_fields(self):
        minimal = {"id": "u1", "email": "a@b.com"}
        result = _record_to_response(minimal)
        assert result.name == ""
        assert result.role == "member"
        assert result.status == "active"
        assert result.metadata == {}


class TestGetMyProfile:
    @pytest.mark.asyncio
    async def test_returns_current_user_profile(self):
        pb = AsyncMock()
        pb.find_record_by_id = AsyncMock(return_value=MOCK_USER_RECORD)

        result = await get_my_profile(ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb)

        assert result.id == "user_123"
        assert result.email == "test@example.com"
        pb.find_record_by_id.assert_called_once_with(
            collection="users",
            record_id="user_admin",
            token="admin_token",
        )


class TestUpdateMyProfile:
    @pytest.mark.asyncio
    async def test_updates_name(self):
        pb = AsyncMock()
        updated_record = {**MOCK_USER_RECORD, "name": "Updated Name"}
        pb.update_record = AsyncMock(return_value=updated_record)

        from app.interface.dto.user import UserProfileUpdateRequest
        body = UserProfileUpdateRequest(name="Updated Name")

        result = await update_my_profile(body=body, ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb)

        assert result.name == "Updated Name"
        pb.update_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_update_returns_current(self):
        pb = AsyncMock()
        pb.find_record_by_id = AsyncMock(return_value=MOCK_USER_RECORD)

        from app.interface.dto.user import UserProfileUpdateRequest
        body = UserProfileUpdateRequest()

        result = await update_my_profile(body=body, ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb)

        assert result.id == "user_123"
        pb.find_record_by_id.assert_called_once()
        pb.update_record.assert_not_called()


class TestListUsers:
    @pytest.mark.asyncio
    async def test_admin_can_list_users(self):
        pb = AsyncMock()
        pb.collection_list = AsyncMock(
            return_value={
                "items": [MOCK_USER_RECORD],
                "totalItems": 1,
                "page": 1,
                "perPage": 30,
                "totalPages": 1,
            }
        )

        result = await list_users(ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb)

        assert result.total == 1
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_member_cannot_list_users(self):
        pb = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await list_users(ctx=_tenant_ctx(MOCK_MEMBER_AUTH), pb=pb)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        pb = AsyncMock()
        pb.collection_list = AsyncMock(
            return_value={
                "items": [],
                "totalItems": 0,
                "page": 1,
                "perPage": 30,
                "totalPages": 0,
            }
        )

        result = await list_users(
            status="active",
            ctx=_tenant_ctx(MOCK_ADMIN_AUTH),
            pb=pb,
        )

        call_kwargs = pb.collection_list.call_args.kwargs
        assert 'status="active"' in call_kwargs["filter_expr"]


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_admin_creates_user_with_temp_password(self):
        pb = AsyncMock()
        created_record = {
            **MOCK_USER_RECORD,
            "id": "new_user_1",
            "email": "new@example.com",
        }
        pb.create_record = AsyncMock(return_value=created_record)

        from app.interface.dto.user import UserCreateRequest
        body = UserCreateRequest(email="new@example.com", name="New User")

        result = await create_user(body=body, auth=MOCK_ADMIN_AUTH, pb=pb)

        assert result.user.email == "new@example.com"
        assert result.temporary_password is not None
        assert len(result.temporary_password) > 0
        pb.create_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_member_cannot_create_user(self):
        pb = AsyncMock()

        from app.interface.dto.user import UserCreateRequest
        body = UserCreateRequest(email="new@example.com")

        with pytest.raises(HTTPException) as exc_info:
            await create_user(body=body, auth=MOCK_MEMBER_AUTH, pb=pb)
        assert exc_info.value.status_code == 403


class TestGetUser:
    @pytest.mark.asyncio
    async def test_admin_gets_user_in_same_tenant(self):
        pb = AsyncMock()
        pb.find_record_by_id = AsyncMock(return_value=MOCK_USER_RECORD)

        result = await get_user(user_id="user_123", ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb)

        assert result.id == "user_123"

    @pytest.mark.asyncio
    async def test_member_cannot_get_user(self):
        pb = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_user(user_id="user_123", ctx=_tenant_ctx(MOCK_MEMBER_AUTH), pb=pb)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_user_from_different_tenant_raises_404(self):
        pb = AsyncMock()
        other_tenant_user = {**MOCK_USER_RECORD, "tenant_id": "tenant_xyz"}
        pb.find_record_by_id = AsyncMock(return_value=other_tenant_user)

        with pytest.raises(HTTPException) as exc_info:
            await get_user(user_id="user_123", ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb)
        assert exc_info.value.status_code == 404


class TestUpdateUser:
    @pytest.mark.asyncio
    async def test_admin_updates_user(self):
        pb = AsyncMock()
        pb.find_record_by_id = AsyncMock(return_value=MOCK_USER_RECORD)
        updated = {**MOCK_USER_RECORD, "name": "Updated"}
        pb.update_record = AsyncMock(return_value=updated)

        from app.interface.dto.user import UserUpdateRequest
        body = UserUpdateRequest(name="Updated")

        result = await update_user(
            user_id="user_123", body=body, ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb
        )

        assert result.name == "Updated"

    @pytest.mark.asyncio
    async def test_member_cannot_update_user(self):
        pb = AsyncMock()

        from app.interface.dto.user import UserUpdateRequest
        body = UserUpdateRequest(name="Updated")

        with pytest.raises(HTTPException) as exc_info:
            await update_user(
                user_id="user_123", body=body, ctx=_tenant_ctx(MOCK_MEMBER_AUTH), pb=pb
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_user_from_different_tenant_raises_404(self):
        pb = AsyncMock()
        other_tenant_user = {**MOCK_USER_RECORD, "tenant_id": "tenant_xyz"}
        pb.find_record_by_id = AsyncMock(return_value=other_tenant_user)

        from app.interface.dto.user import UserUpdateRequest
        body = UserUpdateRequest(name="Updated")

        with pytest.raises(HTTPException) as exc_info:
            await update_user(
                user_id="user_123", body=body, ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb
            )
        assert exc_info.value.status_code == 404


class TestDeleteUser:
    @pytest.mark.asyncio
    async def test_admin_soft_deletes_user(self):
        pb = AsyncMock()
        pb.find_record_by_id = AsyncMock(return_value=MOCK_USER_RECORD)
        pb.update_record = AsyncMock(return_value={})

        result = await delete_user(
            user_id="user_123", ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb
        )

        assert result.status_code == 204
        update_call = pb.update_record.call_args.kwargs
        assert update_call["data"]["status"] == "inactive"

    @pytest.mark.asyncio
    async def test_member_cannot_delete_user(self):
        pb = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await delete_user(user_id="user_123", ctx=_tenant_ctx(MOCK_MEMBER_AUTH), pb=pb)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_user_from_different_tenant_raises_404(self):
        pb = AsyncMock()
        other_tenant_user = {**MOCK_USER_RECORD, "tenant_id": "tenant_xyz"}
        pb.find_record_by_id = AsyncMock(return_value=other_tenant_user)

        with pytest.raises(HTTPException) as exc_info:
            await delete_user(user_id="user_123", ctx=_tenant_ctx(MOCK_ADMIN_AUTH), pb=pb)
        assert exc_info.value.status_code == 404


MOCK_SUPERADMIN = SuperAdminContext(token="pb-api-token")


class TestCreateUserSuperadmin:
    @pytest.mark.asyncio
    async def test_superadmin_creates_user_with_tenant_id(self):
        static_pb = AsyncMock()
        created_record = {
            **MOCK_USER_RECORD,
            "id": "new_user_sa",
            "email": "sa@example.com",
            "tenant_id": "tenant_xyz",
        }
        static_pb.create_record = AsyncMock(return_value=created_record)

        from app.interface.dto.user import UserCreateRequest
        body = UserCreateRequest(
            email="sa@example.com",
            name="SA User",
            tenant_id="tenant_xyz",
            role="owner",
        )

        result = await create_user(
            body=body, auth=None, admin=MOCK_SUPERADMIN, pb=AsyncMock(), static_pb=static_pb
        )

        assert result.user.email == "sa@example.com"
        assert result.user.tenant_id == "tenant_xyz"
        assert result.temporary_password is not None
        static_pb.create_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_superadmin_without_tenant_id_raises_400(self):
        from app.interface.dto.user import UserCreateRequest
        body = UserCreateRequest(email="sa@example.com")

        with pytest.raises(HTTPException) as exc_info:
            await create_user(
                body=body, auth=None, admin=MOCK_SUPERADMIN, pb=AsyncMock(), static_pb=AsyncMock()
            )
        assert exc_info.value.status_code == 400
        assert "tenant_id is required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_user_auth_with_tenant_id_raises_400(self):
        pb = AsyncMock()
        from app.interface.dto.user import UserCreateRequest
        body = UserCreateRequest(
            email="new@example.com",
            tenant_id="tenant_xyz",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_user(body=body, auth=MOCK_ADMIN_AUTH, pb=pb)
        assert exc_info.value.status_code == 400
        assert "tenant_id cannot be specified" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_no_auth_raises_401(self):
        from app.interface.dto.user import UserCreateRequest
        body = UserCreateRequest(email="new@example.com")

        with pytest.raises(HTTPException) as exc_info:
            await create_user(body=body, auth=None, admin=None, pb=AsyncMock(), static_pb=AsyncMock())
        assert exc_info.value.status_code == 401
