from enum import Enum
from typing import Dict, FrozenSet

from fastapi import HTTPException

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


def _resolve_role(auth: AuthContext) -> UserRole:
    role_str = auth.record.get("role", "guest")
    try:
        return UserRole(role_str)
    except ValueError:
        return UserRole.GUEST


def enforce_permission(auth: AuthContext, permission: Permission) -> None:
    allowed = ROLE_PERMISSIONS.get(_resolve_role(auth), frozenset())
    if permission not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {permission.value}",
        )


def has_permission(auth: AuthContext, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(_resolve_role(auth), frozenset())


def can_delete_resources(auth: AuthContext) -> bool:
    return has_permission(auth, Permission.SITES_DELETE)


def can_manage_users(auth: AuthContext) -> bool:
    return has_permission(auth, Permission.USERS_LIST)
