from typing import Optional

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
    name: Optional[str] = None
    page_id: Optional[str] = None


class StorageFileResponse(BaseModel):
    file_id: str
    site_id: str
    page_id: Optional[str] = None
    name: str
    original_name: str
    mime_type: str
    size: int
    status: UploadStatus
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


StorageListResponse = PaginatedResponse[StorageFileResponse]


class StorageUpdateRequest(BaseModel):
    name: Optional[str] = None
    page_id: Optional[str] = None


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
