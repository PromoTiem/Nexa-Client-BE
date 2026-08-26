from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.application.services.site_file_service import SiteFileService
from app.infrastructure.storage.client import StorageClient


def make_service(storage_mock=None):
    if storage_mock is None:
        storage_mock = MagicMock(spec=StorageClient)
    return SiteFileService(
        storage_client=storage_mock,
        max_file_bytes=10 * 1024 * 1024,
    )


class TestSiteFileServiceCreateUpload:
    @pytest.mark.asyncio
    async def test_unsupported_mime_raises_415(self):
        storage = MagicMock(spec=StorageClient)
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(return_value={"id": "site_rec"})

        with pytest.raises(HTTPException) as exc_info:
            await service._create_upload(
                site_id="site_1",
                filename="test.txt",
                content_type="text/plain",
                declared_size=100,
                name="test",
                page_id=None,
                pb=pb,
                token="token",
                user_id="user_1",
            )

        assert exc_info.value.status_code == 415
        assert "Unsupported file type" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_file_too_large_raises_413(self):
        storage = MagicMock(spec=StorageClient)
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(return_value={"id": "site_rec"})

        with pytest.raises(HTTPException) as exc_info:
            await service._create_upload(
                site_id="site_1",
                filename="test.png",
                content_type="image/png",
                declared_size=999 * 1024 * 1024,
                name="test",
                page_id=None,
                pb=pb,
                token="token",
                user_id="user_1",
            )

        assert exc_info.value.status_code == 413
        assert "File too large" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_creates_upload_record(self):
        storage = MagicMock(spec=StorageClient)
        storage.presign_put = AsyncMock(
            return_value={
                "upload_url": "https://upload.url",
                "expires_at": "2026-01-01T00:00:00Z",
                "key": "site_1/test.png",
            }
        )

        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(return_value={"id": "site_rec"})
        pb.create_record = AsyncMock(return_value={"id": "file_rec"})

        result = await service._create_upload(
            site_id="site_1",
            filename="test.png",
            content_type="image/png",
            declared_size=1024,
            name="test",
            page_id=None,
            pb=pb,
            token="token",
            user_id="user_1",
        )

        assert "file_id" in result
        assert result["upload_url"] == "https://upload.url"
        assert result["bucket"] is not None
        pb.create_record.assert_called_once()


class TestSiteFileServiceConfirmUpload:
    @pytest.mark.asyncio
    async def test_idempotent_already_uploaded(self):
        storage = MagicMock(spec=StorageClient)
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            return_value={
                "id": "rec_1",
                "file_id": "file_1",
                "status": "uploaded",
                "bucket": "bucket_1",
                "path": "site_1/test.png",
            }
        )

        result = await service.confirm_upload(
            file_id="file_1",
            pb=pb,
            token="token",
            user_id="user_1",
        )

        assert result["status"] == "uploaded"
        storage.head.assert_not_called()

    @pytest.mark.asyncio
    async def test_object_not_found_raises_409(self):
        storage = MagicMock(spec=StorageClient)
        storage.head = AsyncMock(return_value={"exists": False, "size": 0})
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            return_value={
                "id": "rec_1",
                "file_id": "file_1",
                "status": "pending",
                "bucket": "bucket_1",
                "path": "site_1/test.png",
                "size": 1024,
            }
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_upload(
                file_id="file_1",
                pb=pb,
                token="token",
                user_id="user_1",
            )

        assert exc_info.value.status_code == 409
        assert "Object not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_size_mismatch_raises_422(self):
        storage = MagicMock(spec=StorageClient)
        storage.head = AsyncMock(return_value={"exists": True, "size": 2048})
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            return_value={
                "id": "rec_1",
                "file_id": "file_1",
                "status": "pending",
                "bucket": "bucket_1",
                "path": "site_1/test.png",
                "size": 1024,
            }
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_upload(
                file_id="file_1",
                pb=pb,
                token="token",
                user_id="user_1",
            )

        assert exc_info.value.status_code == 422
        assert "Size mismatch" in str(exc_info.value.detail)


class TestSiteFileServiceListFiles:
    @pytest.mark.asyncio
    async def test_lists_files_for_site(self):
        storage = MagicMock(spec=StorageClient)
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.list_records = AsyncMock(
            return_value={
                "page": 1,
                "perPage": 20,
                "totalItems": 2,
                "totalPages": 1,
                "items": [
                    {"file_id": "f1", "name": "img1.png"},
                    {"file_id": "f2", "name": "img2.png"},
                ],
            }
        )

        result = await service.list_files(
            site_id="site_1",
            page_id=None,
            page=1,
            limit=20,
            pb=pb,
            token="token",
        )

        assert result["totalItems"] == 2
        assert len(result["items"]) == 2
        pb.list_records.assert_called_once()

    @pytest.mark.asyncio
    async def test_lists_files_with_page_filter(self):
        storage = MagicMock(spec=StorageClient)
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.list_records = AsyncMock(
            return_value={
                "page": 1,
                "perPage": 20,
                "totalItems": 1,
                "totalPages": 1,
                "items": [{"file_id": "f1", "name": "img1.png"}],
            }
        )

        result = await service.list_files(
            site_id="site_1",
            page_id="page_1",
            page=1,
            limit=20,
            pb=pb,
            token="token",
        )

        assert result["totalItems"] == 1
        call_kwargs = pb.list_records.call_args.kwargs
        assert 'page_id="page_1"' in call_kwargs["filter"]


class TestSiteFileServiceDelete:
    @pytest.mark.asyncio
    async def test_deletes_object_and_record(self):
        storage = MagicMock(spec=StorageClient)
        storage.delete_object = AsyncMock(return_value=None)
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            return_value={
                "id": "rec_1",
                "file_id": "file_1",
                "bucket": "bucket_1",
                "path": "site_1/test.png",
            }
        )
        pb.delete_record = AsyncMock(return_value=None)

        await service.delete_file(
            file_id="file_1",
            pb=pb,
            token="token",
            user_id="user_1",
        )

        storage.delete_object.assert_called_once()
        pb.delete_record.assert_called_once()


class TestSiteFileServiceBulkDelete:
    @pytest.mark.asyncio
    async def test_bulk_delete_success(self):
        storage = MagicMock(spec=StorageClient)
        storage.delete_object = AsyncMock(return_value=None)
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            side_effect=lambda collection, **kwargs: (
                {
                    "id": "rec_1",
                    "file_id": "file_1",
                    "site_id": "site_1",
                    "bucket": "bucket_1",
                    "path": "site_1/test.png",
                }
                if collection != "sites"
                else {
                    "id": "site_rec",
                    "site_id": "site_1",
                    "tenant_id": "t1",
                }
            )
        )
        pb.delete_record = AsyncMock(return_value=None)

        from app.interface.dependencies import AuthContext

        auth = AuthContext(token="tok", record={"tenant_id": "t1"})

        results = await service.bulk_delete(
            file_ids=["file_1"],
            pb=pb,
            token="token",
            user_id="user_1",
            auth=auth,
        )

        assert len(results) == 1
        assert results[0]["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_bulk_delete_not_found(self):
        storage = MagicMock(spec=StorageClient)
        service = make_service(storage)
        service._allowed_mime = frozenset({"image/png"})

        pb = AsyncMock()
        pb.find_one_by_filter = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Not found")
        )

        results = await service.bulk_delete(
            file_ids=["file_missing"],
            pb=pb,
            token="token",
            user_id="user_1",
        )

        assert len(results) == 1
        assert results[0]["status"] == "not_found"
