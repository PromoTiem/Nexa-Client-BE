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
    page_id: str | None = None


class StorageFileResponse(BaseModel):
    file_id: str
    site_id: str
    page_id: str | None = None
    name: str
    original_name: str
    mime_type: str
    size: int
    status: UploadStatus
    created_at: str | None = None
    updated_at: str | None = None


StorageListResponse = PaginatedResponse[StorageFileResponse]


class StorageUpdateRequest(BaseModel):
    name: str | None = None
    page_id: str | None = None

    @field_validator("name")
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
    "StorageFileResponse",
    "StorageListResponse",
    "StorageUpdateRequest",
    "UploadStatus",
    "UploadUrlRequest",
    "UploadUrlResponse",
]
