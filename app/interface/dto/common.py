from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

BulkDeleteStatus = Literal["deleted", "not_found", "error"]
UploadStatus = Literal["pending", "uploaded"]
ServeStatus = Literal[
    "requested", "verifying", "verified", "serving", "live", "stopped", "failed"
]


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    total_pages: int


class UploadUrlResponse(BaseModel):
    file_id: str
    upload_url: str
    expires_at: str
    bucket: str
    key: str


class DownloadUrlResponse(BaseModel):
    download_url: str
    expires_at: str


class BulkDeleteRequest(BaseModel):
    file_ids: list[str] = Field(max_length=100)


class ItemResult(BaseModel):
    file_id: str
    status: BulkDeleteStatus


class BulkDeleteResponse(BaseModel):
    results: list[ItemResult]
