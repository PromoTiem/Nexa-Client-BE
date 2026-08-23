from typing import Any

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class StyleResponse(BaseModel):
    id: str
    style_id: str
    name: str
    description: str | None = None
    config: dict[str, Any] | None = None
    tailwind_css: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


StyleListResponse = PaginatedResponse[StyleResponse]
