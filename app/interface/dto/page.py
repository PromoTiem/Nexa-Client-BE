from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class PageResponse(BaseModel):
    id: str
    page_id: str
    name: str
    slug: Optional[str] = None
    style_id: Optional[str] = None
    layout: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None
    section_ids: Optional[List[str]] = None
    block_ids: Optional[List[str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


PageListResponse = PaginatedResponse[PageResponse]
