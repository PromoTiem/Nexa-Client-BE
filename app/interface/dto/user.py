from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse

UserRole = Literal["owner", "admin", "member", "guest"]
UserStatus = Literal["active", "inactive", "pending"]


class UserCreateRequest(BaseModel):
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    tenant_id: Optional[str] = None
    role: UserRole = "member"
    metadata: Optional[Dict[str, Any]] = None


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None
    metadata: Optional[Dict[str, Any]] = None


class UserProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    phone: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    avatar: Optional[str] = None
    phone: Optional[str] = None
    tenant_id: str
    role: UserRole
    status: UserStatus
    is_superuser: bool = False
    last_login: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created: str
    updated: str


class UserCreateResponse(BaseModel):
    user: UserResponse
    temporary_password: str


class UserListResponse(PaginatedResponse[UserResponse]):
    pass
