import secrets
from typing import Any, Dict, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    AuthContext, SuperAdminContext, get_admin_context, get_auth_context,
    get_pocketbase_client, get_static_pb_client,
)
from app.interface.dto.user import (
    UserCreateRequest,
    UserCreateResponse,
    UserListResponse,
    UserProfileUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.interface.route_helpers import auth_tenant, build_filter, validate_id

COLLECTION = "users"

router = APIRouter()
logger = get_logger("user_routes")


def _require_admin_role(auth: AuthContext) -> None:
    role = auth.record.get("role", "")
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")


def _record_to_response(record: Dict[str, Any]) -> UserResponse:
    return UserResponse(
        id=record["id"],
        email=record.get("email", ""),
        name=record.get("name", ""),
        avatar=record.get("avatar", ""),
        phone=record.get("phone", ""),
        tenant_id=record.get("tenant_id", ""),
        role=record.get("role", "member"),
        status=record.get("status", "active"),
        last_login=record.get("last_login", ""),
        metadata=record.get("metadata") or {},
        created=record.get("created", ""),
        updated=record.get("updated", ""),
    )


# ── Self-service profile ────────────────────────────────────────


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserResponse:
    record = await pb.find_record_by_id(
        collection=COLLECTION,
        record_id=auth.record["id"],
        token=auth.token,
    )
    return _record_to_response(record)


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    body: UserProfileUpdateRequest,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserResponse:
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        record = await pb.find_record_by_id(
            collection=COLLECTION,
            record_id=auth.record["id"],
            token=auth.token,
        )
        return _record_to_response(record)

    record = await pb.update_record(
        collection=COLLECTION,
        record_id=auth.record["id"],
        data=update_data,
        token=auth.token,
    )
    return _record_to_response(record)


# ── Tenant admin — user CRUD ────────────────────────────────────


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    status: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserListResponse:
    _require_admin_role(auth)
    tenant = auth_tenant(auth)

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
        token=auth.token,
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
    auth: Optional[AuthContext] = Depends(get_auth_context),
    admin: Optional[SuperAdminContext] = Depends(get_admin_context),
    pb: Optional[PocketBaseClient] = Depends(get_pocketbase_client),
    static_pb: Optional[PocketBaseClient] = Depends(get_static_pb_client),
) -> UserCreateResponse:
    if auth:
        _require_admin_role(auth)
        tenant = auth_tenant(auth)
        pb_client = pb
        token = auth.token
        if body.tenant_id:
            raise HTTPException(
                status_code=400,
                detail="tenant_id cannot be specified with user authentication",
            )
    elif admin:
        if not body.tenant_id:
            raise HTTPException(
                status_code=400,
                detail="tenant_id is required for superadmin user creation",
            )
        tenant = body.tenant_id
        pb_client = static_pb
        token = admin.token
    else:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: provide Bearer token or x_api_be_token header",
        )

    temp_password = secrets.token_urlsafe(12)

    record = await pb_client.create_record(
        collection=COLLECTION,
        data={
            "email": body.email,
            "password": temp_password,
            "passwordConfirm": temp_password,
            "name": body.name or "",
            "phone": body.phone or "",
            "tenant_id": tenant,
            "role": body.role,
            "status": "active",
            "metadata": body.metadata or {},
        },
        token=token,
    )

    logger.info(
        "user created",
        extra={"user_id": record["id"], "email": body.email, "tenant": tenant},
    )

    return UserCreateResponse(
        user=_record_to_response(record),
        temporary_password=temp_password,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserResponse:
    _require_admin_role(auth)
    validate_id(user_id, "user_id")

    record = await pb.find_record_by_id(
        collection=COLLECTION,
        record_id=user_id,
        token=auth.token,
    )

    if record.get("tenant_id") != auth_tenant(auth):
        raise HTTPException(status_code=404, detail="User not found")

    return _record_to_response(record)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> UserResponse:
    _require_admin_role(auth)
    validate_id(user_id, "user_id")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        record = await pb.find_record_by_id(
            collection=COLLECTION,
            record_id=user_id,
            token=auth.token,
        )
        if record.get("tenant_id") != auth_tenant(auth):
            raise HTTPException(status_code=404, detail="User not found")
        return _record_to_response(record)

    record = await pb.find_record_by_id(
        collection=COLLECTION,
        record_id=user_id,
        token=auth.token,
    )
    if record.get("tenant_id") != auth_tenant(auth):
        raise HTTPException(status_code=404, detail="User not found")

    updated = await pb.update_record(
        collection=COLLECTION,
        record_id=user_id,
        data=update_data,
        token=auth.token,
    )
    return _record_to_response(updated)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    _require_admin_role(auth)
    validate_id(user_id, "user_id")

    record = await pb.find_record_by_id(
        collection=COLLECTION,
        record_id=user_id,
        token=auth.token,
    )
    if record.get("tenant_id") != auth_tenant(auth):
        raise HTTPException(status_code=404, detail="User not found")

    await pb.update_record(
        collection=COLLECTION,
        record_id=user_id,
        data={"status": "inactive"},
        token=auth.token,
    )

    logger.info("user soft-deleted", extra={"user_id": user_id})

    return Response(status_code=204)
