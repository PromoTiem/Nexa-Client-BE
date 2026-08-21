from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class BuildCreateRequest(BaseModel):
    build_id: str
    site_id: str
    template_id: Optional[str] = None
    content_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class BuildUpdateRequest(BaseModel):
    status: Optional[str] = None
    content_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class BuildResponse(BaseModel):
    id: str
    build_id: str
    site_id: str
    template_id: Optional[str] = None
    status: str
    content_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    error_message: Optional[str] = None
    build_log: Optional[str] = None
    image: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


BuildListResponse = PaginatedResponse[BuildResponse]
