from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from app.application.services.account_service import enforce_account_access
from app.config import Settings, get_settings
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import _bearer, get_pocketbase_client
from app.interface.dto.auth import (
    AuthForgotPasswordRequest,
    AuthForgotPasswordResponse,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthRefreshResponse,
)
from app.interface.limiter import limiter

router = APIRouter()


@router.post("/login", response_model=AuthLoginResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
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
    enforce_account_access(data["record"])
    return AuthLoginResponse(token=data["token"], record=data["record"])


@router.post("/refresh", response_model=AuthRefreshResponse)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AuthRefreshResponse:
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")
    data = await pb.auth_refresh(
        collection=settings.pocketbase_auth_collection,
        token=credentials.credentials,
    )
    enforce_account_access(data["record"])
    return AuthRefreshResponse(token=data["token"], record=data["record"])


@router.post("/forgot-password", response_model=AuthForgotPasswordResponse)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: AuthForgotPasswordRequest,
    settings: Settings = Depends(get_settings),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AuthForgotPasswordResponse:
    await pb.request_password_reset(
        settings.pocketbase_auth_collection, str(body.email)
    )
    return AuthForgotPasswordResponse()
