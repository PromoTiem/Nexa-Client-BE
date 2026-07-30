from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

from app.interface.dto.common import PaginatedResponse


class PropertyField(BaseModel):
    key: str
    label: str
    type: str
    value: Any = None
    required: bool = False
    order_index: int = 0
    placeholder: Optional[str] = None
    default: Any = None
    help_text: Optional[str] = None
    hidden: bool = False
    readonly: bool = False
    # Type-specific attributes
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    rows: Optional[int] = None
    toolbar: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    decimal_places: Optional[int] = None
    options: Optional[List[str]] = None
    max_selections: Optional[int] = None
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    show_time: Optional[bool] = None
    max_size_mb: Optional[float] = None
    allowed_types: Optional[List[str]] = None
    aspect_ratio: Optional[str] = None
    max_images: Optional[int] = None
    schema_: Optional[Dict[str, Any]] = None


class PropertyGroup(BaseModel):
    key: str
    label: str
    fields: List[PropertyField]
    entries: List[Dict[str, Any]] = []
    min_entries: Optional[int] = None
    max_entries: Optional[int] = None


class PropertyCreateRequest(BaseModel):
    property_id: str
    type: Optional[str] = None
    subtype: Optional[str] = None
    name: str
    slug: Optional[str] = None
    status: str = "draft"
    excerpt: Optional[str] = None
    featured_image: Optional[str] = None
    seo: Optional[Dict[str, Any]] = None
    fields: List[PropertyField] = []
    groups: List[PropertyGroup] = []
    metadata: Optional[Dict[str, Any]] = None
    ordering: int = 0

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("draft", "published"):
            raise ValueError("status must be 'draft' or 'published'")
        return v


class PropertyUpdateRequest(BaseModel):
    type: Optional[str] = None
    subtype: Optional[str] = None
    name: Optional[str] = None
    slug: Optional[str] = None
    status: Optional[str] = None
    excerpt: Optional[str] = None
    featured_image: Optional[str] = None
    seo: Optional[Dict[str, Any]] = None
    fields: Optional[List[PropertyField]] = None
    groups: Optional[List[PropertyGroup]] = None
    metadata: Optional[Dict[str, Any]] = None
    ordering: Optional[int] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("draft", "published"):
            raise ValueError("status must be 'draft' or 'published'")
        return v


class PropertyResponse(BaseModel):
    id: str
    property_id: str
    site_id: str
    type: Optional[str] = None
    subtype: Optional[str] = None
    name: str
    slug: Optional[str] = None
    status: str
    excerpt: Optional[str] = None
    featured_image: Optional[str] = None
    seo: Optional[Dict[str, Any]] = None
    published_at: Optional[str] = None
    fields: List[Dict[str, Any]] = []
    groups: List[Dict[str, Any]] = []
    metadata: Optional[Dict[str, Any]] = None
    ordering: int = 0
    deleted_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


PropertyListResponse = PaginatedResponse[PropertyResponse]
