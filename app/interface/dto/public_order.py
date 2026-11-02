from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PublicPaymentMethod = Literal["momo", "cod", "bank"]


class PublicOrderItemCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    property_id: str = Field(min_length=1, description="Item or property identifier")
    quantity: int = Field(gt=0, description="Item quantity, must be greater than zero")
    unit_price: int = Field(ge=0, description="Unit price in VND")
    variation: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class PublicOrderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    customer_name: str = Field(min_length=1, description="Customer full name")
    customer_phone: str | None = Field(
        default=None, description="Customer contact phone number"
    )
    customer_email: str | None = Field(
        default=None, description="Customer contact email address"
    )
    shipping_address: str | dict[str, Any] | None = Field(
        default=None, description="Shipping destination address"
    )
    payment_method: str = Field(
        default="cod", description="Payment method: momo, cod, bank"
    )
    items: list[PublicOrderItemCreate] = Field(
        min_length=1, description="List of order items, non-empty"
    )
    total: int | None = Field(
        default=None, description="Optional explicit total in VND"
    )
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class PublicOrderResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    order_id: str
    status: str = "pending"
    total: int
    currency: str = "VND"
    payment_method: str
    payment_id: str | None = None
    pay_url: str | None = None
    deeplink: str | None = None
    qr_code_url: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    created_at: str | None = None
