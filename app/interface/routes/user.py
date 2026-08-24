import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.config import Settings, get_settings
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.dto.user import (
    UserChangePasswordRequest,
    UserCreateRequest,
    UserCreateResponse,
    UserListResponse,
    UserProfileUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import build_filter, validate_id

COLLECTION = "users"

router = APIRouter()
logger = get_logger("user_routes")


def _record_to_response(record: Dict[str, Any]) -> UserResponse:
    return UserResponse(
        id=record["id"],
        email=record.get("email", ""),
        name=record.get("name", ""),
        avatar=record.get("avatar", ""),
        phone=record.get("phone", ""),
        tenant_id=record.get("tenant_id", ""),
        role=record.get("role", "guest"),
        status=record.get("status", "active"),
        first_auth=record.get("first_auth", False),
        last_login=record.get("last_login", ""),
        metadata=record.get("metadata") or {},
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


# ── Self-service profile ────────────────────────────────────────


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserResponse:
    record = await pb.find_record_by_id(
        collection=COLLECTION,
        record_id=ctx.user_id,
        token=ctx.token,
    )
    return _record_to_response(record)


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    body: UserProfileUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserResponse:
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        record = await pb.find_record_by_id(
            collection=COLLECTION,
            record_id=ctx.user_id,
            token=ctx.token,
        )
        return _record_to_response(record)

    record = await pb.update_record(
        collection=COLLECTION,
        record_id=ctx.user_id,
        data=update_data,
        token=ctx.token,
    )
    return _record_to_response(record)
@router.post("/me/password", status_code=204)
async def change_my_password(
    body: UserChangePasswordRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    settings: Settings = Depends(get_settings),
) -> Response:
    # 1. Verify old password
    try:
        await pb.auth_with_password(
            collection=settings.pocketbase_auth_collection,
            identity=ctx.auth.record["email"],
            password=body.old_password,
        )
    except HTTPException:
        raise HTTPException(status_code=400, detail="Invalid old password")

    # 2. Update password and set first_auth to False
    await pb.update_record(
        collection=COLLECTION,
        record_id=ctx.user_id,
        data={
            "password": body.password,
            "passwordConfirm": body.password_confirm,
            "first_auth": False,
        },
        token=ctx.token,
    )

    logger.info("user password changed", extra={"user_id": ctx.user_id})

    return Response(status_code=204)





# ── Tenant admin — user CRUD ────────────────────────────────────


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    status: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserListResponse:
    enforce_permission(ctx.auth, Permission.USERS_LIST)
    tenant = ctx.tenant_id

    filter_parts = [f'tenant_id="{tenant}"']
    if status:
        filter_parts.append(f'status="{status}"')
    if role:
        filter_parts.append(f'role="{role}"')
    if search:
        filter_parts.append(f'(name~"{search}" || email~"{search}")')

    filter_expr = build_filter(filter_parts)

    result = await pb.collection_list(
        collection=COLLECTION,
        filter_expr=filter_expr,
        page=page,
        per_page=per_page,
        sort="-created",
        token=ctx.token,
    )

    return UserListResponse(
        items=[_record_to_response(r) for r in result.get("items", [])],
        total=result.get("totalItems", 0),
        page=result.get("page", 1),
        per_page=result.get("perPage", 30),
        total_pages=result.get("totalPages", 1),
    )


@router.post("", response_model=UserCreateResponse, status_code=201)
async def create_user(
    body: UserCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserCreateResponse:
    enforce_permission(ctx.auth, Permission.USERS_CREATE)

    if body.tenant_id and body.tenant_id != ctx.tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot create user in a different tenant",
        )

    temp_password = secrets.token_urlsafe(12)

    record = await pb.create_record(
        collection=COLLECTION,
        data={
            "email": body.email,
            "password": temp_password,
            "passwordConfirm": temp_password,
            "name": body.name or "",
            "phone": body.phone or "",
            "tenant_id": ctx.tenant_id,
            "role": body.role,
            "status": "active",
            "first_auth": True,
            "metadata": body.metadata or {},
        },
        token=ctx.token,
    )

    logger.info(
        "user created",
        extra={"user_id": record["id"], "email": body.email, "tenant": ctx.tenant_id},
    )

    return UserCreateResponse(
        user=_record_to_response(record),
        temporary_password=temp_password,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserResponse:
    enforce_permission(ctx.auth, Permission.USERS_LIST)
    validate_id(user_id, "user_id")

    record = await pb.find_record_by_id(
        collection=COLLECTION,
        record_id=user_id,
        token=ctx.token,
    )

    ctx.enforce_owns(record)

    return _record_to_response(record)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserResponse:
    enforce_permission(ctx.auth, Permission.USERS_UPDATE)
    validate_id(user_id, "user_id")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        record = await pb.find_record_by_id(
            collection=COLLECTION,
            record_id=user_id,
            token=ctx.token,
        )
        ctx.enforce_owns(record)
        return _record_to_response(record)

    record = await pb.find_record_by_id(
        collection=COLLECTION,
        record_id=user_id,
        token=ctx.token,
    )
    ctx.enforce_owns(record)

    updated = await pb.update_record(
        collection=COLLECTION,
        record_id=user_id,
        data=update_data,
        token=ctx.token,
    )
    return _record_to_response(updated)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    enforce_permission(ctx.auth, Permission.USERS_DELETE)
    validate_id(user_id, "user_id")

    record = await pb.find_record_by_id(
        collection=COLLECTION,
        record_id=user_id,
        token=ctx.token,
    )
    ctx.enforce_owns(record)

    await pb.update_record(
        collection=COLLECTION,
        record_id=user_id,
        data={"status": "inactive"},
        token=ctx.token,
    )

    logger.info("user soft-deleted", extra={"user_id": user_id})

    return Response(status_code=204)
