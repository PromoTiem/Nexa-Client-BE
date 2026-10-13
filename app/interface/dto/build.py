from typing import Any, Literal

from pydantic import BaseModel, field_validator

from app.interface.dto.common import PaginatedResponse


class BuildConfigInput(BaseModel):
    @field_validator("config", check_fields=False)
    @classmethod
    def reject_attempt_metadata(cls, value):
        if isinstance(value, dict) and "_nexa_attempt" in value:
            raise ValueError("Build attempt metadata is server-owned")
        return value


class BuildCreateRequest(BuildConfigInput):
    build_id: str
    site_id: str
    template_id: str | None = None
    content_id: str | None = None
    config: dict[str, Any] | None = None


class BuildUpdateRequest(BuildConfigInput):
    status: Literal["queued", "building", "completed", "failed"] | None = None
    content_id: str | None = None
    config: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def reject_null_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("must not be null")
        return value


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
