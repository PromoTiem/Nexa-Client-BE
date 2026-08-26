from typing import Any, Literal

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse, ServeStatus

SiteStatus = Literal["draft", "building", "live", "error"]


class SiteCreateRequest(BaseModel):
    site_id: str
    template_id: str
    domain: str
    config: dict[str, Any] | None = None
    status: SiteStatus | None = None
    default: bool | None = False


class SiteUpdateRequest(BaseModel):
    template_id: str | None = None
    domain: str | None = None
    domain_id: str | None = None
    config: dict[str, Any] | None = None
    status: SiteStatus | None = None
    default: bool | None = None


class SiteResponse(BaseModel):
    id: str
    site_id: str
    tenant_id: str | None = None
    template_id: str | None = None
    domain: str | None = None
    domain_id: str | None = None
    config: dict[str, Any] | None = None
    status: SiteStatus | None = None
    bucket_name: str | None = None
    bucket_description: str | None = None
    bucket_public: bool = False
    serve_status: ServeStatus | None = None
    serve_stage_log: dict[str, str] | None = None
    default: bool | None = False
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


SiteListResponse = PaginatedResponse[SiteResponse]
