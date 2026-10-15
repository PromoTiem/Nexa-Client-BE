from fastapi import APIRouter, Depends, Query, Response

from app.application.services.transactional_service import TransactionalService
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_tenant_context,
)
from app.interface.dto.transactional import (
    AvailabilityCreateRequest,
    AvailabilityListResponse,
    AvailabilityResponse,
    AvailabilityUpdateRequest,
    BookingCreateRequest,
    BookingDetail,
    BookingListResponse,
    BookingSummary,
    BookingUpdateRequest,
    FakePaymentRequest,
    OrderCreateRequest,
    OrderDetail,
    OrderItemCreate,
    OrderItemResponse,
    OrderListResponse,
    OrderSummary,
    OrderUpdateRequest,
    PaymentCreateRequest,
    PaymentResponse,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import validate_id
from app.interface.transaction_dependencies import (
    get_transaction_client as get_pocketbase_client,
)

router = APIRouter()
service = TransactionalService()


def _user_id(ctx: TenantContext) -> str | None:
    return ctx.auth.record.get("id")


@router.post("/sites/{site_id}/orders", response_model=OrderDetail, status_code=201)
async def create_order(
    site_id: str,
    body: OrderCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> OrderDetail:
    enforce_permission(ctx.auth, Permission.ORDERS_MANAGE)
    validate_id(site_id, "site_id")
    await ctx.enforce_site(pb, site_id)
    return OrderDetail(
        **await service.create_order(
            pb, ctx.token, site_id, body.model_dump(), _user_id(ctx)
        )
    )


@router.get("/sites/{site_id}/orders", response_model=OrderListResponse)
async def list_orders(
    site_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> OrderListResponse:
    enforce_permission(ctx.auth, Permission.ORDERS_VIEW)
    validate_id(site_id, "site_id")
    await ctx.enforce_site(pb, site_id)
    result = await service.list_orders(
        pb,
        ctx.token,
        site_id,
        page=page,
        per_page=per_page,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    items = [OrderSummary(**record) for record in result.get("items", [])]
    return OrderListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/orders/{order_id}", response_model=OrderDetail)
async def get_order(
    order_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> OrderDetail:
    enforce_permission(ctx.auth, Permission.ORDERS_VIEW)
    validate_id(order_id, "order_id")
    result = await service.get_order(pb, ctx.token, order_id)
    await ctx.enforce_site(pb, result["site_id"])
    return OrderDetail(**result)


@router.patch("/orders/{order_id}", response_model=OrderDetail)
async def update_order(
    order_id: str,
    body: OrderUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> OrderDetail:
    enforce_permission(ctx.auth, Permission.ORDERS_MANAGE)
    validate_id(order_id, "order_id")
    current = await service.get_order(pb, ctx.token, order_id)
    await ctx.enforce_site(pb, current["site_id"])
    result = await service.update_order(
        pb,
        ctx.token,
        order_id,
        body.model_dump(exclude_unset=True),
        _user_id(ctx),
        current["site_id"],
    )
    return OrderDetail(**result)


@router.post(
    "/orders/{order_id}/items", response_model=OrderItemResponse, status_code=201
)
async def add_order_item(
    order_id: str,
    body: OrderItemCreate,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> OrderItemResponse:
    enforce_permission(ctx.auth, Permission.ORDERS_MANAGE)
    validate_id(order_id, "order_id")
    order = await service.get_order(pb, ctx.token, order_id)
    await ctx.enforce_site(pb, order["site_id"])
    return OrderItemResponse(
        **await service.add_order_item(
            pb, ctx.token, order_id, body.model_dump(), _user_id(ctx)
        )
    )


@router.delete("/order_items/{item_id}", status_code=204)
async def delete_order_item(
    item_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    enforce_permission(ctx.auth, Permission.ORDERS_MANAGE)
    validate_id(item_id, "item_id")
    item = await pb.find_one_by_filter(
        "order_items", f'item_id="{item_id}"', token=ctx.token
    )
    order = await service.get_order(pb, ctx.token, item["order_id"])
    await ctx.enforce_site(pb, order["site_id"])
    await service.delete_order_item(pb, ctx.token, item_id, _user_id(ctx))
    return Response(status_code=204)


@router.post(
    "/orders/{order_id}/payments", response_model=PaymentResponse, status_code=201
)
async def add_payment(
    order_id: str,
    body: PaymentCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PaymentResponse:
    enforce_permission(ctx.auth, Permission.ORDERS_MANAGE)
    validate_id(order_id, "order_id")
    order = await service.get_order(pb, ctx.token, order_id)
    await ctx.enforce_site(pb, order["site_id"])
    return PaymentResponse(
        **await service.add_payment(
            pb, ctx.token, order_id, body.model_dump(), _user_id(ctx)
        )
    )


@router.get("/orders/{order_id}/payments", response_model=list[PaymentResponse])
async def list_payments(
    order_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> list[PaymentResponse]:
    enforce_permission(ctx.auth, Permission.ORDERS_VIEW)
    validate_id(order_id, "order_id")
    order = await service.get_order(pb, ctx.token, order_id)
    await ctx.enforce_site(pb, order["site_id"])
    return [
        PaymentResponse(**item)
        for item in await service.list_payments(pb, ctx.token, order_id)
    ]


@router.post("/orders/{order_id}/fake-payment", response_model=PaymentResponse)
async def fake_payment(
    order_id: str,
    body: FakePaymentRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PaymentResponse:
    """Simulate a full payment without charging money; retries reuse the same key."""
    enforce_permission(ctx.auth, Permission.ORDERS_MANAGE)
    validate_id(order_id, "order_id")
    order = await service.get_order(pb, ctx.token, order_id)
    await ctx.enforce_site(pb, order["site_id"])
    return PaymentResponse(
        **await service.fake_payment(
            pb, ctx.token, order_id, body.idempotency_key, _user_id(ctx)
        )
    )


@router.delete("/orders/{order_id}", status_code=204)
async def delete_order(
    order_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    enforce_permission(ctx.auth, Permission.ORDERS_MANAGE)
    validate_id(order_id, "order_id")
    result = await service.get_order(pb, ctx.token, order_id)
    await ctx.enforce_site(pb, result["site_id"])
    await service.delete_order(pb, ctx.token, order_id, _user_id(ctx))
    return Response(status_code=204)


@router.post("/sites/{site_id}/bookings", response_model=BookingDetail, status_code=201)
async def create_booking(
    site_id: str,
    body: BookingCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BookingDetail:
    enforce_permission(ctx.auth, Permission.BOOKINGS_MANAGE)
    validate_id(site_id, "site_id")
    await ctx.enforce_site(pb, site_id)
    return BookingDetail(
        **await service.create_booking(
            pb, ctx.token, site_id, body.model_dump(), _user_id(ctx)
        )
    )


@router.get("/sites/{site_id}/bookings", response_model=BookingListResponse)
async def list_bookings(
    site_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    status: str | None = Query(None),
    date: str | None = Query(None),
    property_id: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BookingListResponse:
    enforce_permission(ctx.auth, Permission.BOOKINGS_VIEW)
    validate_id(site_id, "site_id")
    await ctx.enforce_site(pb, site_id)
    result = await service.list_bookings(
        pb,
        ctx.token,
        site_id,
        page=page,
        per_page=per_page,
        status=status,
        date=date,
        property_id=property_id,
    )
    property_ids = [record.get("property_id", "") for record in result.get("items", [])]
    properties = await service._properties(pb, ctx.token, site_id, property_ids)
    items = []
    for record in result.get("items", []):
        prop = properties.get(record.get("property_id"))
        items.append(
            BookingSummary(
                **{**record, "property_name": prop.get("name") if prop else None}
            )
        )
    return BookingListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.get("/bookings/{booking_id}", response_model=BookingDetail)
async def get_booking(
    booking_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BookingDetail:
    enforce_permission(ctx.auth, Permission.BOOKINGS_VIEW)
    validate_id(booking_id, "booking_id")
    result = await service.get_booking(pb, ctx.token, booking_id)
    await ctx.enforce_site(pb, result["site_id"])
    return BookingDetail(**result)


@router.patch("/bookings/{booking_id}", response_model=BookingDetail)
async def update_booking(
    booking_id: str,
    body: BookingUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> BookingDetail:
    enforce_permission(ctx.auth, Permission.BOOKINGS_MANAGE)
    validate_id(booking_id, "booking_id")
    current = await service.get_booking(pb, ctx.token, booking_id)
    await ctx.enforce_site(pb, current["site_id"])
    result = await service.update_booking(
        pb,
        ctx.token,
        booking_id,
        body.model_dump(exclude_unset=True),
        _user_id(ctx),
        current["site_id"],
    )
    return BookingDetail(**result)


@router.delete("/bookings/{booking_id}", status_code=204)
async def delete_booking(
    booking_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    enforce_permission(ctx.auth, Permission.BOOKINGS_MANAGE)
    validate_id(booking_id, "booking_id")
    result = await service.get_booking(pb, ctx.token, booking_id)
    await ctx.enforce_site(pb, result["site_id"])
    await service.delete_booking(pb, ctx.token, booking_id, _user_id(ctx))
    return Response(status_code=204)


@router.post(
    "/sites/{site_id}/availability",
    response_model=AvailabilityResponse,
    status_code=201,
)
async def create_availability(
    site_id: str,
    body: AvailabilityCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AvailabilityResponse:
    enforce_permission(ctx.auth, Permission.BOOKINGS_MANAGE)
    validate_id(site_id, "site_id")
    await ctx.enforce_site(pb, site_id)
    return AvailabilityResponse(
        **await service.create_availability(
            pb, ctx.token, site_id, body.model_dump(), _user_id(ctx)
        )
    )


@router.get("/sites/{site_id}/availability", response_model=AvailabilityListResponse)
async def list_availability(
    site_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    property_id: str | None = Query(None),
    day_of_week: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AvailabilityListResponse:
    enforce_permission(ctx.auth, Permission.BOOKINGS_VIEW)
    validate_id(site_id, "site_id")
    await ctx.enforce_site(pb, site_id)
    result = await service.list_availability(
        pb,
        ctx.token,
        site_id,
        page=page,
        per_page=per_page,
        property_id=property_id,
        day_of_week=day_of_week,
    )
    return AvailabilityListResponse(
        items=[AvailabilityResponse(**item) for item in result.get("items", [])],
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.patch("/availability/{availability_id}", response_model=AvailabilityResponse)
async def update_availability(
    availability_id: str,
    body: AvailabilityUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> AvailabilityResponse:
    enforce_permission(ctx.auth, Permission.BOOKINGS_MANAGE)
    validate_id(availability_id, "availability_id")
    current = await pb.find_one_by_filter(
        "availability", f'availability_id="{availability_id}"', token=ctx.token
    )
    await ctx.enforce_site(pb, current["site_id"])
    return AvailabilityResponse(
        **await service.update_availability(
            pb,
            ctx.token,
            availability_id,
            body.model_dump(exclude_unset=True),
            _user_id(ctx),
        )
    )


@router.delete("/availability/{availability_id}", status_code=204)
async def delete_availability(
    availability_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> Response:
    enforce_permission(ctx.auth, Permission.BOOKINGS_MANAGE)
    validate_id(availability_id, "availability_id")
    current = await pb.find_one_by_filter(
        "availability", f'availability_id="{availability_id}"', token=ctx.token
    )
    await ctx.enforce_site(pb, current["site_id"])
    await service.delete_availability(pb, ctx.token, availability_id)
    return Response(status_code=204)
