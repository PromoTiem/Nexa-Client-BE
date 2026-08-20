from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class TemplateResponse(BaseModel):
    id: str
    template_id: str
    name: str
    style_id: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None
    page_ids: Optional[List[str]] = None
    version: Optional[int] = None
    is_valid: Optional[bool] = None
    is_default: Optional[bool] = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    expanded_style: Optional[Dict[str, Any]] = None
    expanded_pages: Optional[List[Dict[str, Any]]] = None
    warnings: Optional[List[str]] = None


TemplateListResponse = PaginatedResponse[TemplateResponse]
