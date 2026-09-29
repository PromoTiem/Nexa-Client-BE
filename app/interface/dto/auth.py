from typing import Any

from pydantic import BaseModel, EmailStr


class AuthLoginRequest(BaseModel):
    identity: str
    password: str
    identity_field: str | None = None


class AuthForgotPasswordRequest(BaseModel):
    email: EmailStr


class AuthForgotPasswordResponse(BaseModel):
    message: str = "If the account exists, password reset instructions will be emailed."


class AuthResponse(BaseModel):
    token: str
    record: dict[str, Any]


# Backward-compatible aliases
AuthLoginResponse = AuthResponse
AuthRefreshResponse = AuthResponse
