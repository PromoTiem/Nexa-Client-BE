from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.config import Settings, get_settings
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import get_pocketbase_client, _bearer
from app.interface.dto.auth import (
    AuthLoginRequest, AuthLoginResponse, AuthRefreshResponse
)

router = APIRouter()


@router.post("/login", response_model=AuthLoginResponse)
async def login(
    body: AuthLoginRequest,
    settings: Settings = Depends(get_settings),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AuthLoginResponse:
    data = await pb.auth_with_password(
        collection=settings.pocketbase_auth_collection,
        identity=body.identity,
        password=body.password,
        identity_field=body.identity_field,
    )
    return AuthLoginResponse(token=data["token"], record=data["record"])


@router.post("/refresh", response_model=AuthRefreshResponse)
async def refresh(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AuthRefreshResponse:
    if not credentials:
        raise HTTPException(
            status_code=401, detail="Missing authorization token"
        )
    data = await pb.auth_refresh(
        collection=settings.pocketbase_auth_collection,
        token=credentials.credentials,
    )
    return AuthRefreshResponse(token=data["token"], record=data["record"])
