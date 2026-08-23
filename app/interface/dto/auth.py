from typing import Any

from pydantic import BaseModel


class AuthLoginRequest(BaseModel):
    identity: str
    password: str
    identity_field: str | None = None


class AuthResponse(BaseModel):
    token: str
    record: dict[str, Any]


# Backward-compatible aliases
AuthLoginResponse = AuthResponse
AuthRefreshResponse = AuthResponse
