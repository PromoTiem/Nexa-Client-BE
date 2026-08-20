from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class StyleResponse(BaseModel):
    id: str
    style_id: str
    name: str
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    tailwind_css: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


StyleListResponse = PaginatedResponse[StyleResponse]
