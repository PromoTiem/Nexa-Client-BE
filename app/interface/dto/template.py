from typing import Any

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class TemplateResponse(BaseModel):
    id: str
    template_id: str
    name: str
    style_id: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    description: str | None = None
    page_ids: list[str] | None = None
    version: int | None = None
    is_valid: bool | None = None
    is_default: bool | None = False
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    expanded_style: dict[str, Any] | None = None
    expanded_pages: list[dict[str, Any]] | None = None
    warnings: list[str] | None = None


TemplateListResponse = PaginatedResponse[TemplateResponse]
