from typing import Dict, Literal, Optional

from pydantic import BaseModel

from app.interface.dto.common import ServeStatus

ManualServeStatus = Literal["requested", "verifying", "verified", "failed"]


class ServeStatusPatchRequest(BaseModel):
    status: ManualServeStatus


class ServeStateResponse(BaseModel):
    site_id: str
    serve_status: Optional[ServeStatus] = None
    serve_stage_log: Dict[str, str] = {}


class SiteServeResponse(BaseModel):
    site_id: str
    build_id: str
    pages_url: str
    custom_domain: str
    deployment_url: str
    serve_status: Optional[ServeStatus] = None


class SiteStopResponse(BaseModel):
    site_id: str
    status: str
    custom_domain: str
    pages_url: str
    serve_status: Optional[ServeStatus] = None


class PipelineBuild(BaseModel):
    latest_build_id: Optional[str] = None
    build_status: Optional[str] = None


class PipelineServe(BaseModel):
    status: Optional[ServeStatus] = None
    stage_log: Dict[str, str] = {}


class PipelineDomain(BaseModel):
    domain_id: Optional[str] = None
    domain: Optional[str] = None
    status: Optional[str] = None


class PipelineResponse(BaseModel):
    site_id: str
    build: Optional[PipelineBuild] = None
    serve: PipelineServe
    domain: Optional[PipelineDomain] = None
