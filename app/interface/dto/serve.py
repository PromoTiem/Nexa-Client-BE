from typing import Literal

from pydantic import BaseModel

from app.interface.dto.common import ServeStatus

ManualServeStatus = Literal["requested", "verifying", "verified", "failed"]


class ServeStatusPatchRequest(BaseModel):
    status: ManualServeStatus


class ServeStateResponse(BaseModel):
    site_id: str
    serve_status: ServeStatus | None = None
    serve_stage_log: dict[str, str] = {}


class SiteServeResponse(BaseModel):
    site_id: str
    build_id: str
    pages_url: str
    custom_domain: str
    deployment_url: str
    serve_status: ServeStatus | None = None


class SiteStopResponse(BaseModel):
    site_id: str
    status: str
    custom_domain: str
    pages_url: str
    serve_status: ServeStatus | None = None


class PipelineBuild(BaseModel):
    latest_build_id: str | None = None
    build_status: str | None = None


class PipelineServe(BaseModel):
    status: ServeStatus | None = None
    stage_log: dict[str, str] = {}


class PipelineDomain(BaseModel):
    domain_id: str | None = None
    domain: str | None = None
    status: str | None = None


class PipelineResponse(BaseModel):
    site_id: str
    build: PipelineBuild | None = None
    serve: PipelineServe
    domain: PipelineDomain | None = None
