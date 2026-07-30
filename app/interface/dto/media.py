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
    is_default: Optional[bool] = None
    original_file_id: Optional[str] = None
    page_id: Optional[str] = None


class MediaResponse(BaseModel):
    file_id: str
    site_id: str
    page_id: Optional[str] = None
    original_file_id: Optional[str] = None
    name: str
    original_name: str
    mime_type: str
    size: int
    status: UploadStatus
    is_default: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


MediaListResponse = PaginatedResponse[MediaResponse]


class MediaUpdateRequest(BaseModel):
    name: Optional[str] = None
    is_default: Optional[bool] = None
    original_file_id: Optional[str] = None
    page_id: Optional[str] = None


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
