from typing import Any, Literal

from pydantic import BaseModel, Field

from app.interface.dto.common import PaginatedResponse

OrderStatus = Literal["pending", "paid", "fulfilled", "cancelled"]
BookingStatus = Literal["pending", "confirmed", "completed", "cancelled"]


class PropertyReference(BaseModel):
    property_id: str
    site_id: str
    name: str | None = None
    type: str | None = None
    status: str | None = None


class OrderItemResponse(BaseModel):
    item_id: str
    order_id: str
    property_id: str
    quantity: float = 0
    unit_price: float = 0
    total_price: float = 0
    variation: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    property: PropertyReference | None = None


class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    method: str
    amount: float = 0
    currency: str = "USD"
    status: str
    transaction_ref: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class OrderSummary(BaseModel):
    order_id: str
    site_id: str
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    status: OrderStatus
    total: float = 0
    currency: str = "USD"
    item_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class OrderDetail(OrderSummary):
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    items: list[OrderItemResponse] = Field(default_factory=list)
    payments: list[PaymentResponse] = Field(default_factory=list)


class OrderItemCreate(BaseModel):
    property_id: str
    quantity: float = Field(gt=0, allow_inf_nan=False)
    unit_price: float = Field(ge=0, allow_inf_nan=False)
    variation: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class OrderCreateRequest(BaseModel):
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    currency: str = "USD"
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderUpdateRequest(BaseModel):
    status: OrderStatus | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class PaymentCreateRequest(BaseModel):
    method: str
    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: str = "USD"
    status: str = "pending"
    transaction_ref: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class BookingSummary(BaseModel):
    booking_id: str
    site_id: str
    property_id: str
    property_name: str | None = None
    customer_name: str
    customer_email: str
    customer_phone: str | None = None
    date: str
    start_time: str
    end_time: str
    status: BookingStatus
    created_at: str | None = None
    updated_at: str | None = None


class BookingDetail(BookingSummary):
    notes: str | None = None
    metadata: dict[str, Any] | None = None
    fields: list[dict[str, Any]] = Field(default_factory=list)
    property: PropertyReference | None = None
    legacy_property_id: str | None = None


class BookingCreateRequest(BaseModel):
    property_id: str
    customer_name: str = Field(min_length=1)
    customer_email: str = Field(min_length=1)
    customer_phone: str | None = None
    date: str
    start_time: str
    end_time: str
    notes: str | None = None
    fields: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class BookingUpdateRequest(BaseModel):
    status: BookingStatus | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    notes: str | None = None
    fields: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class AvailabilityResponse(BaseModel):
    availability_id: str
    site_id: str
    property_id: str
    day_of_week: str
    start_time: str
    end_time: str
    max_bookings: int = 0
    is_active: bool = True
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AvailabilityCreateRequest(BaseModel):
    property_id: str
    day_of_week: str
    start_time: str
    end_time: str
    max_bookings: int = Field(default=0, ge=0)
    is_active: bool = True
    metadata: dict[str, Any] | None = None


class AvailabilityUpdateRequest(BaseModel):
    property_id: str | None = None
    day_of_week: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    max_bookings: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


OrderListResponse = PaginatedResponse[OrderSummary]
BookingListResponse = PaginatedResponse[BookingSummary]
AvailabilityListResponse = PaginatedResponse[AvailabilityResponse]
