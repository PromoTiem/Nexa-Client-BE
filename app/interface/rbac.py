from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, Set

from fastapi import Depends, HTTPException

from app.interface.auth_models import AuthContext


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


class Permission(str, Enum):
    SITES_LIST = "sites:list"
    SITES_CREATE = "sites:create"
    SITES_UPDATE = "sites:update"
    SITES_DELETE = "sites:delete"

    PROPERTIES_LIST = "properties:list"
    PROPERTIES_CREATE = "properties:create"
    PROPERTIES_UPDATE = "properties:update"
    PROPERTIES_DELETE = "properties:delete"

    USERS_LIST = "users:list"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"

    TEMPLATES_LIST = "templates:list"
    STYLES_LIST = "styles:list"
    BLOCKS_LIST = "blocks:list"
    PAGES_LIST = "pages:list"
    SECTIONS_LIST = "sections:list"

    BUILDS_LIST = "builds:list"
    BUILDS_CREATE = "builds:create"
    BUILDS_DELETE = "builds:delete"

    SERVE_ACCESS = "serve:access"

    MEDIA_UPLOAD = "media:upload"
    MEDIA_LIST = "media:list"
    MEDIA_DELETE = "media:delete"

    STORAGE_ACCESS = "storage:access"


ROLE_PERMISSIONS: Dict[UserRole, FrozenSet[Permission]] = {
    UserRole.OWNER: frozenset({
        Permission.SITES_LIST,
        Permission.SITES_CREATE,
        Permission.SITES_UPDATE,
        Permission.SITES_DELETE,
        Permission.PROPERTIES_LIST,
        Permission.PROPERTIES_CREATE,
        Permission.PROPERTIES_UPDATE,
        Permission.PROPERTIES_DELETE,
        Permission.TEMPLATES_LIST,
        Permission.STYLES_LIST,
        Permission.BLOCKS_LIST,
        Permission.PAGES_LIST,
        Permission.SECTIONS_LIST,
        Permission.USERS_LIST,
        Permission.USERS_CREATE,
        Permission.USERS_UPDATE,
        Permission.USERS_DELETE,
        Permission.BUILDS_LIST,
        Permission.BUILDS_CREATE,
        Permission.BUILDS_DELETE,
        Permission.SERVE_ACCESS,
        Permission.MEDIA_UPLOAD,
        Permission.MEDIA_LIST,
        Permission.MEDIA_DELETE,
        Permission.STORAGE_ACCESS,
    }),
    UserRole.ADMIN: frozenset({
        Permission.SITES_LIST,
        Permission.SITES_CREATE,
        Permission.SITES_UPDATE,
        Permission.SITES_DELETE,
        Permission.PROPERTIES_LIST,
        Permission.PROPERTIES_CREATE,
        Permission.PROPERTIES_UPDATE,
        Permission.PROPERTIES_DELETE,
        Permission.TEMPLATES_LIST,
        Permission.STYLES_LIST,
        Permission.BLOCKS_LIST,
        Permission.PAGES_LIST,
        Permission.SECTIONS_LIST,
        Permission.USERS_LIST,
        Permission.USERS_CREATE,
        Permission.USERS_UPDATE,
        Permission.USERS_DELETE,
        Permission.BUILDS_LIST,
        Permission.BUILDS_CREATE,
        Permission.BUILDS_DELETE,
        Permission.SERVE_ACCESS,
        Permission.MEDIA_UPLOAD,
        Permission.MEDIA_LIST,
        Permission.MEDIA_DELETE,
        Permission.STORAGE_ACCESS,
    }),
    UserRole.MEMBER: frozenset({
        Permission.SITES_LIST,
        Permission.SITES_CREATE,
        Permission.SITES_UPDATE,
        Permission.PROPERTIES_LIST,
        Permission.PROPERTIES_CREATE,
        Permission.PROPERTIES_UPDATE,
        Permission.TEMPLATES_LIST,
        Permission.STYLES_LIST,
        Permission.BLOCKS_LIST,
        Permission.PAGES_LIST,
        Permission.SECTIONS_LIST,
        Permission.BUILDS_LIST,
        Permission.BUILDS_CREATE,
        Permission.SERVE_ACCESS,
        Permission.MEDIA_UPLOAD,
        Permission.MEDIA_LIST,
        Permission.STORAGE_ACCESS,
    }),
    UserRole.GUEST: frozenset({
        Permission.SITES_LIST,
        Permission.PROPERTIES_LIST,
        Permission.TEMPLATES_LIST,
        Permission.STYLES_LIST,
        Permission.BLOCKS_LIST,
        Permission.PAGES_LIST,
        Permission.SECTIONS_LIST,
        Permission.BUILDS_LIST,
        Permission.MEDIA_LIST,
    }),
}


@dataclass
class RoleGuard:
    allowed_roles: FrozenSet[UserRole]
    required_permission: Permission = field(default=None)

    def __post_init__(self):
        if self.required_permission is not None:
            self._allowed_roles = self.allowed_roles
        else:
            self._allowed_roles = self.allowed_roles

    def check(self, auth: AuthContext) -> None:
        role_str = auth.record.get("role", "guest")
        try:
            role = UserRole(role_str)
        except ValueError:
            role = UserRole.GUEST

        if role not in self._allowed_roles:
            role_names = ", ".join(r.value for r in self._allowed_roles)
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient role. Required one of: {role_names}",
            )

        if self.required_permission is not None:
            allowed = ROLE_PERMISSIONS.get(role, frozenset())
            if self.required_permission not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {self.required_permission.value}",
                )


def require_role(*roles: str):
    allowed = frozenset(UserRole(r) for r in roles)
    guard = RoleGuard(allowed_roles=allowed)

    def _checker(auth: AuthContext = Depends(_get_auth)):
        guard.check(auth)
        return auth

    return _checker


def require_permission(permission: Permission, *, roles: Set[UserRole] = None):
    if roles is not None:
        allowed = frozenset(roles)
    else:
        allowed = frozenset(
            role for role, perms in ROLE_PERMISSIONS.items()
            if permission in perms
        )
    guard = RoleGuard(allowed_roles=allowed, required_permission=permission)

    def _checker(auth: AuthContext = Depends(_get_auth)):
        guard.check(auth)
        return auth

    return _checker


def _get_auth():
    from app.interface.dependencies import get_auth_context
    return get_auth_context


def enforce_permission(auth: AuthContext, permission: Permission) -> None:
    role_str = auth.record.get("role", "guest")
    try:
        role = UserRole(role_str)
    except ValueError:
        role = UserRole.GUEST
    allowed = ROLE_PERMISSIONS.get(role, frozenset())
    if permission not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {permission.value}",
        )


def has_permission(auth: AuthContext, permission: Permission) -> bool:
    role_str = auth.record.get("role", "guest")
    try:
        role = UserRole(role_str)
    except ValueError:
        role = UserRole.GUEST
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def can_delete_resources(auth: AuthContext) -> bool:
    return has_permission(auth, Permission.SITES_DELETE)


def can_manage_users(auth: AuthContext) -> bool:
    return has_permission(auth, Permission.USERS_LIST)


_ROLE_HIERARCHY: Dict[UserRole, int] = {
    UserRole.OWNER: 0,
    UserRole.ADMIN: 1,
    UserRole.MEMBER: 2,
    UserRole.GUEST: 3,
}


def check_role_permission(caller_role: UserRole, target_role: UserRole) -> None:
    """Raise 403 if the caller is not allowed to assign the target role.

    Rules:
    - Each role can only assign roles strictly lower in the hierarchy.
    - owner > admin > member > guest
    - No one can assign the owner role (not even another owner).
    """
    if _ROLE_HIERARCHY[caller_role] >= _ROLE_HIERARCHY[target_role]:
        raise HTTPException(
            status_code=403,
            detail="Cannot assign equal or higher role",
        )
