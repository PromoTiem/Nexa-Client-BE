from typing import Any

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class BuildCreateRequest(BaseModel):
    build_id: str
    site_id: str
    template_id: str | None = None
    content_id: str | None = None
    config: dict[str, Any] | None = None


class BuildUpdateRequest(BaseModel):
    status: str | None = None
    content_id: str | None = None
    config: dict[str, Any] | None = None


class BuildResponse(BaseModel):
    id: str
    build_id: str
    site_id: str
    template_id: str | None = None
    status: str
    content_id: str | None = None
    config: dict[str, Any] | None = None
    description: str | None = None
    error_message: str | None = None
    build_log: str | None = None
    image: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


BuildListResponse = PaginatedResponse[BuildResponse]
