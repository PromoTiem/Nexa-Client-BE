from typing import Any

from pydantic import BaseModel


class AuthLoginRequest(BaseModel):
    identity: str
    password: str
    identity_field: str | None = None


class AuthForgotPasswordRequest(BaseModel):
    email: str


class AuthForgotPasswordResponse(BaseModel):
    temporary_password: str


class AuthResponse(BaseModel):
    token: str
    record: dict[str, Any]


# Backward-compatible aliases
AuthLoginResponse = AuthResponse
AuthRefreshResponse = AuthResponse
