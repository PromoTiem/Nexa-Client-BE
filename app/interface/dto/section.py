from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class SectionResponse(BaseModel):
    id: str
    section_id: str
    name: str
    layout: Optional[str] = None
    order_index: Optional[int] = None
    block_ids: Optional[List[str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


SectionListResponse = PaginatedResponse[SectionResponse]
