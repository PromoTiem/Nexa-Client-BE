import pytest
from fastapi import HTTPException

from app.interface.auth_models import AuthContext
from app.interface.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    RoleGuard,
    UserRole,
    can_delete_resources,
    can_manage_users,
    has_permission,
)

MOCK_OWNER = AuthContext(
    token="owner_token",
    record={
        "id": "user_owner",
        "email": "owner@example.com",
        "tenant_id": "tenant_abc",
        "role": "owner",
    },
)

MOCK_ADMIN = AuthContext(
    token="admin_token",
    record={
        "id": "user_admin",
        "email": "admin@example.com",
        "tenant_id": "tenant_abc",
        "role": "admin",
    },
)

MOCK_MEMBER = AuthContext(
    token="member_token",
    record={
        "id": "user_member",
        "email": "member@example.com",
        "tenant_id": "tenant_abc",
        "role": "member",
    },
)

MOCK_GUEST = AuthContext(
    token="guest_token",
    record={
        "id": "user_guest",
        "email": "guest@example.com",
        "tenant_id": "tenant_abc",
        "role": "guest",
    },
)

MOCK_NO_ROLE = AuthContext(
    token="no_role_token",
    record={
        "id": "user_no_role",
        "email": "norole@example.com",
        "tenant_id": "tenant_abc",
    },
)


class TestUserRolePermissions:
    def test_owner_has_all_permissions(self):
        for perm in Permission:
            assert has_permission(MOCK_OWNER, perm)

    def test_admin_has_most_permissions(self):
        assert has_permission(MOCK_ADMIN, Permission.SITES_LIST)
        assert has_permission(MOCK_ADMIN, Permission.SITES_DELETE)
        assert has_permission(MOCK_ADMIN, Permission.USERS_LIST)
        assert has_permission(MOCK_ADMIN, Permission.USERS_CREATE)
        assert has_permission(MOCK_ADMIN, Permission.USERS_UPDATE)
        assert has_permission(MOCK_ADMIN, Permission.USERS_DELETE)

    def test_member_has_limited_permissions(self):
        assert has_permission(MOCK_MEMBER, Permission.SITES_LIST)
        assert has_permission(MOCK_MEMBER, Permission.SITES_CREATE)
        assert has_permission(MOCK_MEMBER, Permission.SITES_UPDATE)
        assert not has_permission(MOCK_MEMBER, Permission.SITES_DELETE)
        assert not has_permission(MOCK_MEMBER, Permission.USERS_LIST)

    def test_guest_has_readonly_permissions(self):
        assert has_permission(MOCK_GUEST, Permission.SITES_LIST)
        assert has_permission(MOCK_GUEST, Permission.PROPERTIES_LIST)
        assert has_permission(MOCK_GUEST, Permission.MEDIA_LIST)
        assert not has_permission(MOCK_GUEST, Permission.SITES_CREATE)
        assert not has_permission(MOCK_GUEST, Permission.MEDIA_UPLOAD)

    def test_no_role_defaults_to_guest(self):
        assert has_permission(MOCK_NO_ROLE, Permission.SITES_LIST)
        assert not has_permission(MOCK_NO_ROLE, Permission.SITES_CREATE)


class TestRoleGuard:
    def test_guard_allows_owner(self):
        guard = RoleGuard(allowed_roles=frozenset({UserRole.OWNER}))
        guard.check(MOCK_OWNER)

    def test_guard_allows_multiple_roles(self):
        guard = RoleGuard(allowed_roles=frozenset({UserRole.OWNER, UserRole.ADMIN}))
        guard.check(MOCK_OWNER)
        guard.check(MOCK_ADMIN)

    def test_guard_denies_unauthorized_role(self):
        guard = RoleGuard(allowed_roles=frozenset({UserRole.OWNER}))
        with pytest.raises(HTTPException) as exc_info:
            guard.check(MOCK_MEMBER)
        assert exc_info.value.status_code == 403

    def test_guard_with_permission_check(self):
        guard = RoleGuard(
            allowed_roles=frozenset({UserRole.OWNER}),
            required_permission=Permission.USERS_DELETE,
        )
        guard.check(MOCK_OWNER)
        with pytest.raises(HTTPException) as exc_info:
            guard.check(MOCK_ADMIN)
        assert exc_info.value.status_code == 403

    def test_guard_denies_unknown_role(self):
        guard = RoleGuard(allowed_roles=frozenset({UserRole.OWNER}))
        unknown = AuthContext(
            token="unknown",
            record={"id": "u1", "role": "unknown_role"},
        )
        with pytest.raises(HTTPException) as exc_info:
            guard.check(unknown)
        assert exc_info.value.status_code == 403


class TestHelperFunctions:
    def test_can_delete_resources(self):
        assert can_delete_resources(MOCK_OWNER)
        assert can_delete_resources(MOCK_ADMIN)
        assert not can_delete_resources(MOCK_MEMBER)
        assert not can_delete_resources(MOCK_GUEST)

    def test_can_manage_users(self):
        assert can_manage_users(MOCK_OWNER)
        assert can_manage_users(MOCK_ADMIN)
        assert not can_manage_users(MOCK_MEMBER)
        assert not can_manage_users(MOCK_GUEST)


class TestPermissionMatrix:
    def test_all_roles_have_permissions(self):
        for role in UserRole:
            perms = ROLE_PERMISSIONS[role]
            assert len(perms) > 0

    def test_owner_permissions_superset(self):
        owner_perms = ROLE_PERMISSIONS[UserRole.OWNER]
        for role in UserRole:
            if role != UserRole.OWNER:
                assert ROLE_PERMISSIONS[role].issubset(owner_perms)

    def test_admin_cannot_delete_users(self):
        admin_perms = ROLE_PERMISSIONS[UserRole.ADMIN]
        assert Permission.USERS_DELETE in admin_perms

    def test_member_cannot_delete(self):
        member_perms = ROLE_PERMISSIONS[UserRole.MEMBER]
        assert Permission.SITES_DELETE not in member_perms
        assert Permission.PROPERTIES_DELETE not in member_perms
        assert Permission.MEDIA_DELETE not in member_perms

    def test_guest_cannot_write(self):
        guest_perms = ROLE_PERMISSIONS[UserRole.GUEST]
        for perm in Permission:
            if perm not in (
                Permission.SITES_LIST,
                Permission.PROPERTIES_LIST,
                Permission.MEDIA_LIST,
                Permission.TEMPLATES_LIST,
                Permission.STYLES_LIST,
                Permission.BLOCKS_LIST,
                Permission.PAGES_LIST,
                Permission.SECTIONS_LIST,
                Permission.BUILDS_LIST,
            ):
                assert perm not in guest_perms
