from typing import Any

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class PageResponse(BaseModel):
    id: str
    page_id: str
    name: str
    slug: str | None = None
    style_id: str | None = None
    layout: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
    section_ids: list[str] | None = None
    block_ids: list[str] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


PageListResponse = PaginatedResponse[PageResponse]
