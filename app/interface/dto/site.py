from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse, ServeStatus

SiteStatus = Literal["draft", "building", "live", "error"]


class SiteCreateRequest(BaseModel):
    site_id: str
    tenant_id: str
    template_id: str
    domain: str
    config: Optional[Dict[str, Any]] = None
    status: Optional[SiteStatus] = None
    default: Optional[bool] = False


class SiteUpdateRequest(BaseModel):
    template_id: Optional[str] = None
    domain: Optional[str] = None
    domain_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    status: Optional[SiteStatus] = None
    default: Optional[bool] = None


class SiteResponse(BaseModel):
    id: str
    site_id: str
    tenant_id: Optional[str] = None
    template_id: Optional[str] = None
    domain: Optional[str] = None
    domain_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    status: Optional[SiteStatus] = None
    bucket_name: Optional[str] = None
    bucket_description: Optional[str] = None
    bucket_public: bool = False
    serve_status: Optional[ServeStatus] = None
    serve_stage_log: Optional[Dict[str, str]] = None
    default: Optional[bool] = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


SiteListResponse = PaginatedResponse[SiteResponse]
