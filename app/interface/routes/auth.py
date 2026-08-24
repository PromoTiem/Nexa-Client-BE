from typing import Optional

import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.config import Settings, get_settings
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import get_pocketbase_client, _bearer
from app.interface.dto.auth import (
    AuthLoginRequest, AuthLoginResponse, AuthRefreshResponse,
    AuthForgotPasswordRequest, AuthForgotPasswordResponse
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


@router.post("/forgot-password", response_model=AuthForgotPasswordResponse)
async def forgot_password(
    body: AuthForgotPasswordRequest,
    settings: Settings = Depends(get_settings),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AuthForgotPasswordResponse:
    # 1. Admin Auth
    admin_auth = await pb.auth_admin(
        email=settings.pocketbase_admin_email,
        password=settings.pocketbase_admin_password,
    )
    admin_token = admin_auth["token"]

    # 2. Find user by email
    users = await pb.collection_list(
        collection=settings.pocketbase_auth_collection,
        filter_expr=f'email = "{body.email}"',
        token=admin_token,
    )
    if not users.get("items"):
        raise HTTPException(status_code=404, detail="User not found")

    user_record = users["items"][0]

    # 3. Generate temp password
    temp_password = secrets.token_urlsafe(12)

    # 4. Update user
    await pb.update_record(
        collection=settings.pocketbase_auth_collection,
        record_id=user_record["id"],
        data={
            "password": temp_password,
            "passwordConfirm": temp_password,
            "first_auth": True,
        },
        token=admin_token,
    )

    return AuthForgotPasswordResponse(temporary_password=temp_password)
