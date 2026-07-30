from typing import Any, Dict, Optional

from app.application.services.site_file_service import SiteFileService
from app.infrastructure.pocketbase.client import PocketBaseClient

COLLECTION = "media"

DEFAULT_ALLOWED_MIME = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document",
    }
)


class MediaService(SiteFileService):
    """``media`` collection: images/docs keyed at ``{site_id}/...``.

    Adds the media-only ``is_default`` / ``original_file_id`` fields and keeps
    the historical ``list_media`` / ``delete_media`` method names.
    """

    COLLECTION = COLLECTION
    DEFAULT_ALLOWED_MIME = DEFAULT_ALLOWED_MIME
    _NOUN = "media"

    # historical names kept for routes/tests; base provides the behavior
    list_media = SiteFileService.list_files
    delete_media = SiteFileService.delete_file

    async def create_upload(
        self,
        site_id: str,
        filename: str,
        content_type: str,
        declared_size: int,
        name: Optional[str],
        is_default: bool,
        page_id: Optional[str],
        pb: PocketBaseClient,
        token: str,
        user_id: Optional[str],
        original_file_id: Optional[str] = None,
    ) -> Dict[str, Any]:
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
            extra_fields={
                "is_default": is_default,
                "original_file_id": original_file_id,
            },
        )
