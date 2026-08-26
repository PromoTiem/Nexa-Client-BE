from typing import Any

from pydantic import BaseModel, field_validator

from app.interface.dto.common import PaginatedResponse


class PropertyField(BaseModel):
    key: str
    label: str
    type: str
    value: Any = None
    required: bool = False
    order_index: int = 0
    placeholder: str | None = None
    default: Any = None
    help_text: str | None = None
    hidden: bool = False
    readonly: bool = False
    # Type-specific attributes
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    rows: int | None = None
    toolbar: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    prefix: str | None = None
    suffix: str | None = None
    decimal_places: int | None = None
    options: list[str] | None = None
    max_selections: int | None = None
    min_date: str | None = None
    max_date: str | None = None
    show_time: bool | None = None
    max_size_mb: float | None = None
    allowed_types: list[str] | None = None
    aspect_ratio: str | None = None
    max_images: int | None = None
    schema_: dict[str, Any] | None = None


class PropertyGroup(BaseModel):
    key: str
    label: str
    fields: list[PropertyField]
    entries: list[dict[str, Any]] = []
    min_entries: int | None = None
    max_entries: int | None = None


class PropertyCreateRequest(BaseModel):
    property_id: str
    type: str | None = None
    subtype: str | None = None
    name: str
    slug: str | None = None
    status: str = "draft"
    excerpt: str | None = None
    featured_image: str | None = None
    seo: dict[str, Any] | None = None
    fields: list[PropertyField] = []
    groups: list[PropertyGroup] = []
    metadata: dict[str, Any] | None = None
    ordering: int = 0

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("draft", "published"):
            raise ValueError("status must be 'draft' or 'published'")
        return v


class PropertyUpdateRequest(BaseModel):
    type: str | None = None
    subtype: str | None = None
    name: str | None = None
    slug: str | None = None
    status: str | None = None
    excerpt: str | None = None
    featured_image: str | None = None
    seo: dict[str, Any] | None = None
    fields: list[PropertyField] | None = None
    groups: list[PropertyGroup] | None = None
    metadata: dict[str, Any] | None = None
    ordering: int | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("draft", "published"):
            raise ValueError("status must be 'draft' or 'published'")
        return v


class PropertyResponse(BaseModel):
    id: str
    property_id: str
    site_id: str
    type: str | None = None
    subtype: str | None = None
    name: str
    slug: str | None = None
    status: str
    excerpt: str | None = None
    featured_image: str | None = None
    seo: dict[str, Any] | None = None
    published_at: str | None = None
    fields: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    metadata: dict[str, Any] | None = None
    ordering: int = 0
    deleted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


PropertyListResponse = PaginatedResponse[PropertyResponse]
