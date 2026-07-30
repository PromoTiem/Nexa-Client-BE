import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.application.services.bucket_resolver import ensure_site_bucket
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.storage.client import StorageClient

if TYPE_CHECKING:
    from app.interface.dependencies import AuthContext


class SiteFileService:
    """Shared lifecycle (pending -> uploaded) for per-site file collections.

    MediaService and StorageFileService subclass this; they differ only in the
    PocketBase collection, the MIME allowlist, the object-key prefix inside the
    per-site bucket, and a few extra record fields. Bucket is always resolved
    from the site record via ensure_site_bucket(); StorageClient is the source
    of truth for object keys and is never modified here.

    Subclasses MUST set ``COLLECTION``, ``DEFAULT_ALLOWED_MIME`` and ``_NOUN``,
    and MAY override ``_object_prefix``.
    """

    COLLECTION: str = ""
    DEFAULT_ALLOWED_MIME: frozenset = frozenset()
    _NOUN: str = "file"  # used in log + error messages

    def __init__(
        self,
        storage_client: StorageClient,
        max_file_bytes: int,
        allowed_mime: Optional[frozenset] = None,
    ) -> None:
        self._storage = storage_client
        self._max_file_bytes = max_file_bytes
        self._allowed_mime = allowed_mime or self.DEFAULT_ALLOWED_MIME
        self._logger = get_logger(f"{self._NOUN}_service")

    @property
    def max_file_bytes(self) -> int:
        return self._max_file_bytes

    # ----- per-feature hooks ------------------------------------------- #

    def _object_prefix(self, site_id: str) -> str:
        """Prefix passed to presign_put; StorageClient appends the filename."""
        return site_id

    # ----- queries ----------------------------------------------------- #

    async def get_record(
        self, file_id: str, pb: PocketBaseClient, token: str
    ) -> Dict[str, Any]:
        return await pb.find_one_by_filter(
            collection=self.COLLECTION,
            filter_expr=f'file_id="{file_id}"',
            token=token,
        )

    async def list_files(
        self,
        site_id: str,
        page_id: Optional[str],
        page: int,
        limit: int,
        pb: PocketBaseClient,
        token: str,
    ) -> Dict[str, Any]:
        filter_expr = f'site_id="{site_id}"'
        if page_id:
            filter_expr += f' && page_id="{page_id}"'
        return await pb.list_records(
            collection=self.COLLECTION,
            token=token,
            filter=filter_expr,
            sort="-created_at",
            page=page,
            per_page=limit,
        )

    async def get_download_url(
        self, file_id: str, pb: PocketBaseClient, token: str
    ) -> Tuple[str, str]:
        record = await self.get_record(file_id, pb, token)
        if record.get("status") != "uploaded":
            raise HTTPException(
                status_code=409,
                detail=f"{self._NOUN.capitalize()} upload is not completed yet",
            )
        r = await self._storage.presign_get(record["bucket"], record["path"])
        return r["download_url"], r["expires_at"]

    # ----- upload lifecycle -------------------------------------------- #

    async def _create_upload(
        self,
        *,
        site_id: str,
        filename: str,
        content_type: str,
        declared_size: int,
        name: Optional[str],
        page_id: Optional[str],
        pb: PocketBaseClient,
        token: str,
        user_id: Optional[str],
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # 1. site must exist
        await pb.find_one_by_filter(
            collection="sites",
            filter_expr=f'site_id="{site_id}"',
            token=token,
        )
        # 2. MIME allowlist
        if content_type not in self._allowed_mime:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type: {content_type}",
            )
        # 3. declared size limit
        if declared_size > self._max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File too large: {declared_size} bytes "
                    f"(max {self._max_file_bytes})"
                ),
            )

        # 4. ensure bucket exists (creates S3 bucket + updates site if needed)
        bucket = await ensure_site_bucket(site_id, pb, self._storage, token)

        # 5. storage mints bucket/key + presigned PUT url
        r = await self._storage.presign_put(
            bucket, self._object_prefix(site_id), filename, content_type
        )
        key = r["key"]

        file_id = f"file_{uuid.uuid4().hex[:12]}"
        data: Dict[str, Any] = {
            "status": "pending",
            "file_id": file_id,
            "site_id": site_id,
            "page_id": page_id,
            "name": name or filename,
            "original_name": filename,
            "mime_type": content_type,
            "size": declared_size,
            "bucket": bucket,
            "path": key,
            "metadata": {},
            **(extra_fields or {}),
        }
        await pb.create_record(
            collection=self.COLLECTION,
            data=data,
            token=token,
            user_id=user_id,
        )
        self._logger.info(
            f"{self._NOUN} upload created",
            extra={
                "file_id": file_id,
                "site_id": site_id,
                "size": declared_size,
            },
        )
        return {
            "file_id": file_id,
            "upload_url": r["upload_url"],
            "expires_at": r["expires_at"],
            "bucket": bucket,
            "key": key,
        }

    async def confirm_upload(
        self,
        file_id: str,
        pb: PocketBaseClient,
        token: str,
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        record = await self.get_record(file_id, pb, token)

        # idempotent: already confirmed -> return as-is, no HEAD re-check
        if record.get("status") == "uploaded":
            return record

        h = await self._storage.head(record["bucket"], record["path"])
        if not h["exists"]:
            raise HTTPException(
                status_code=409,
                detail="Object not found in storage; upload not completed",
            )
        if h["size"] != record["size"]:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Size mismatch: stored {h['size']} bytes, "
                    f"declared {record['size']}"
                ),
            )

        if h.get("content_type") and record.get("mime_type"):
            stored_ct = h["content_type"].split(";")[0].strip().lower()
            declared_ct = record["mime_type"].split(";")[0].strip().lower()
            if stored_ct != declared_ct and stored_ct != "application/octet-stream":
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Content-Type mismatch: stored {stored_ct}, "
                        f"declared {declared_ct}"
                    ),
                )

        updated = await pb.update_record(
            collection=self.COLLECTION,
            record_id=record["id"],
            data={"status": "uploaded"},
            token=token,
            user_id=user_id,
        )
        self._logger.info(
            f"{self._NOUN} upload confirmed", extra={"file_id": file_id}
        )
        return updated

    # ----- metadata + deletion ----------------------------------------- #

    async def update_metadata(
        self,
        file_id: str,
        updates: Dict[str, Any],
        pb: PocketBaseClient,
        token: str,
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        record = await self.get_record(file_id, pb, token)
        return await pb.update_record(
            collection=self.COLLECTION,
            record_id=record["id"],
            data=updates,
            token=token,
            user_id=user_id,
        )

    async def delete_file(
        self,
        file_id: str,
        pb: PocketBaseClient,
        token: str,
        user_id: Optional[str] = None,
    ) -> None:
        record = await self.get_record(file_id, pb, token)
        # Object first: if delete_record fails afterwards the record points at
        # a missing object (download will 404); the alternative orphans the
        # object. Matches prior philosophy.
        await self._storage.delete_object(record["bucket"], record["path"])
        await pb.delete_record(
            collection=self.COLLECTION,
            record_id=record["id"],
            token=token,
        )

    async def bulk_delete(
        self,
        file_ids: List[str],
        pb: PocketBaseClient,
        token: str,
        user_id: Optional[str] = None,
        auth: Optional["AuthContext"] = None,
    ) -> List[Dict[str, str]]:
        from app.interface.route_helpers import auth_tenant

        results: List[Dict[str, str]] = []
        tenant = auth_tenant(auth) if auth else None
        for file_id in file_ids:
            try:
                record = await self.get_record(file_id, pb, token)
            except HTTPException as exc:
                status = "not_found" if exc.status_code == 404 else "error"
                results.append({"file_id": file_id, "status": status})
                continue

            # Per-file tenant isolation: verify the file's site belongs to the caller.
            if tenant:
                site_id = record.get("site_id")
                if site_id:
                    try:
                        site = await pb.find_one_by_filter(
                            collection="sites",
                            filter_expr=f'site_id="{site_id}"',
                            token=token,
                        )
                        if site.get("tenant_id") != tenant:
                            results.append(
                                {"file_id": file_id, "status": "not_found"}
                            )
                            continue
                    except HTTPException:
                        results.append(
                            {"file_id": file_id, "status": "not_found"}
                        )
                        continue

            try:
                await self._storage.delete_object(
                    record["bucket"], record["path"]
                )
                await pb.delete_record(
                    collection=self.COLLECTION,
                    record_id=record["id"],
                    token=token,
                )
                results.append({"file_id": file_id, "status": "deleted"})
            except Exception:  # noqa: BLE001 - report per-id, keep going
                self._logger.warning(
                    "bulk delete item failed", extra={"file_id": file_id}
                )
                results.append({"file_id": file_id, "status": "error"})
        return results
