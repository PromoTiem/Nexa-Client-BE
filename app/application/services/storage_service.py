from typing import Any

from app.application.services.site_file_service import SiteFileService
from app.infrastructure.pocketbase.client import PocketBaseClient

COLLECTION = "storage"

DEFAULT_ALLOWED_MIME = frozenset(
    {
        "application/json",
        "text/plain",
        "text/csv",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


class StorageFileService(SiteFileService):
    """``storage`` collection: json/docs isolated under ``{site_id}/storage/``."""

    COLLECTION = COLLECTION
    DEFAULT_ALLOWED_MIME = DEFAULT_ALLOWED_MIME
    _NOUN = "storage"

    def _object_prefix(self, site_id: str) -> str:
        return f"{site_id}/storage"

    async def create_upload(
        self,
        site_id: str,
        filename: str,
        content_type: str,
        declared_size: int,
        name: str | None,
        page_id: str | None,
        pb: PocketBaseClient,
        token: str,
        user_id: str | None,
    ) -> dict[str, Any]:
        return await self._create_upload(
            site_id=site_id,
            filename=filename,
            content_type=content_type,
            declared_size=declared_size,
            name=name,
            page_id=page_id,
            pb=pb,
            token=token,
            user_id=user_id,
        )
