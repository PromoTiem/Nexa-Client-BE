from typing import Any

from pydantic import BaseModel, field_validator

from app.interface.dto.common import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    DownloadUrlResponse,
    ItemResult,
    PaginatedResponse,
    UploadStatus,
    UploadUrlResponse,
)


class UploadUrlRequest(BaseModel):
    site_id: str
    filename: str
    content_type: str
    size: int
    name: str | None = None
    is_default: bool | None = None
    original_file_id: str | None = None
    page_id: str | None = None


class MediaResponse(BaseModel):
    file_id: str
    site_id: str
    page_id: str | None = None
    original_file_id: str | None = None
    name: str
    original_name: str
    mime_type: str
    size: int
    status: UploadStatus
    is_default: bool = False
    created_at: str | None = None
    updated_at: str | None = None


MediaListResponse = PaginatedResponse[MediaResponse]


class MediaUpdateRequest(BaseModel):
    name: str | None = None
    is_default: bool | None = None
    original_file_id: str | None = None
    page_id: str | None = None

    @field_validator("name", "is_default")
    @classmethod
    def reject_null_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("must not be null")
        return value


__all__ = [
    "BulkDeleteRequest",
    "BulkDeleteResponse",
    "DownloadUrlResponse",
    "ItemResult",
    "MediaListResponse",
    "MediaResponse",
    "MediaUpdateRequest",
    "UploadStatus",
    "UploadUrlRequest",
    "UploadUrlResponse",
]
