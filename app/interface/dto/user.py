from typing import Any, Literal

from pydantic import BaseModel, EmailStr

from app.interface.dto.common import PaginatedResponse

UserRole = Literal["owner", "admin", "member", "guest"]
UserStatus = Literal["active", "inactive", "pending"]


class UserCreateRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    phone: str | None = None
    tenant_id: str | None = None
    role: UserRole = "member"
    metadata: dict[str, Any] | None = None


class UserUpdateRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    role: UserRole | None = None
    status: UserStatus | None = None
    metadata: dict[str, Any] | None = None


class UserProfileUpdateRequest(BaseModel):
    name: str | None = None
    avatar: str | None = None
    phone: str | None = None
    metadata: dict[str, Any] | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None = None
    avatar: str | None = None
    phone: str | None = None
    tenant_id: str
    role: UserRole
    status: UserStatus
    last_login: str | None = None
    metadata: dict[str, Any] | None = None
    created: str
    updated: str


class UserCreateResponse(BaseModel):
    user: UserResponse
    temporary_password: str


class UserListResponse(PaginatedResponse[UserResponse]):
    pass
