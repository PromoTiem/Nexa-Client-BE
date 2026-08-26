from pydantic import BaseModel

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
