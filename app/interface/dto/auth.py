from typing import Any, Dict, Optional

from pydantic import BaseModel


class AuthLoginRequest(BaseModel):
    identity: str
    password: str
    identity_field: Optional[str] = None


class AuthResponse(BaseModel):
    token: str
    record: Dict[str, Any]


# Backward-compatible aliases
AuthLoginResponse = AuthResponse
AuthRefreshResponse = AuthResponse
