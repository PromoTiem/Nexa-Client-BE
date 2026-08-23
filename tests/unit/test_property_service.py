from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.services.property_service import PropertyService


class TestPropertyServiceCreate:
    @pytest.mark.asyncio
    async def test_creates_property_success(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(return_value={"totalItems": 0, "items": []})
        pb.create_record = AsyncMock(
            return_value={
                "id": "rec_1",
                "property_id": "prop_1",
                "site_id": "site_1",
                "name": "Test Product",
                "slug": "test-product",
                "type": "product",
                "status": "draft",
                "fields": [],
                "groups": [],
                "ordering": 0,
            }
        )

        service = PropertyService()
        result = await service.create_property(
            pb=pb,
            token="token",
            user_id="user_1",
            site_id="site_1",
            data={
                "property_id": "prop_1",
                "name": "Test Product",
                "slug": "test-product",
                "type": "product",
                "status": "draft",
                "fields": [],
                "groups": [],
            },
        )

        assert result["property_id"] == "prop_1"
        assert result["name"] == "Test Product"
        pb.create_record.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_slug_raises_409(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(
            return_value={"totalItems": 1, "items": [{"id": "rec_1"}]}
        )

        service = PropertyService()

        with pytest.raises(HTTPException) as exc_info:
            await service.create_property(
                pb=pb,
                token="token",
                user_id="user_1",
                site_id="site_1",
                data={
                    "property_id": "prop_1",
                    "name": "Test",
                    "slug": "duplicate-slug",
                    "type": "product",
                    "status": "draft",
                    "fields": [],
                    "groups": [],
                },
            )

        assert exc_info.value.status_code == 409
        assert "already exists" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_category_without_slug_raises_422(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(return_value={"totalItems": 0, "items": []})

        service = PropertyService()

        with pytest.raises(HTTPException) as exc_info:
            await service.create_property(
                pb=pb,
                token="token",
                user_id="user_1",
                site_id="site_1",
                data={
                    "property_id": "cat_1",
                    "name": "Category",
                    "type": "category",
                    "status": "draft",
                    "fields": [],
                    "groups": [],
                },
            )

        assert exc_info.value.status_code == 422
        assert "must have a slug" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_fields_raises_400(self):
        pb = AsyncMock()

        service = PropertyService()

        with pytest.raises(HTTPException) as exc_info:
            await service.create_property(
                pb=pb,
                token="token",
                user_id="user_1",
                site_id="site_1",
                data={
                    "property_id": "prop_1",
                    "name": "Test",
                    "fields": [{"key": "x"}],
                    "groups": [],
                },
            )

        assert exc_info.value.status_code == 400


class TestPropertyServiceUpdate:
    @pytest.mark.asyncio
    async def test_updates_property_success(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(return_value={"totalItems": 0, "items": []})
        pb.update_record = AsyncMock(
            return_value={
                "id": "rec_1",
                "property_id": "prop_1",
                "site_id": "site_1",
                "name": "Updated Name",
                "slug": "test-product",
                "type": "product",
                "status": "draft",
                "fields": [],
                "groups": [],
                "ordering": 0,
            }
        )

        service = PropertyService()
        record = {
            "id": "rec_1",
            "property_id": "prop_1",
            "site_id": "site_1",
            "name": "Old Name",
            "slug": "test-product",
            "type": "product",
            "status": "draft",
            "fields": [],
            "groups": [],
        }

        result = await service.update_property(
            pb=pb,
            token="token",
            user_id="user_1",
            record=record,
            updates={"name": "Updated Name"},
        )

        assert result["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_publish_sets_published_at(self):
        pb = AsyncMock()
        pb.list_records = AsyncMock(return_value={"totalItems": 0, "items": []})
        pb.update_record = AsyncMock(
            return_value={
                "id": "rec_1",
                "property_id": "prop_1",
                "site_id": "site_1",
                "name": "Test",
                "slug": "test",
                "type": "product",
                "status": "published",
                "published_at": "2026-01-01T00:00:00+00:00",
                "fields": [],
                "groups": [],
                "ordering": 0,
            }
        )

        service = PropertyService()
        record = {
            "id": "rec_1",
            "property_id": "prop_1",
            "site_id": "site_1",
            "name": "Test",
            "slug": "test",
            "type": "product",
            "status": "draft",
            "fields": [],
            "groups": [],
        }

        result = await service.update_property(
            pb=pb,
            token="token",
            user_id="user_1",
            record=record,
            updates={"status": "published"},
        )

        assert result["status"] == "published"
        assert result.get("published_at") is not None


class TestPropertyServiceSoftDelete:
    @pytest.mark.asyncio
    async def test_soft_delete_sets_deleted_at(self):
        pb = AsyncMock()
        pb.update_record = AsyncMock(
            return_value={
                "id": "rec_1",
                "property_id": "prop_1",
                "deleted_at": "2026-01-01T00:00:00+00:00",
            }
        )

        service = PropertyService()
        record = {
            "id": "rec_1",
            "property_id": "prop_1",
            "site_id": "site_1",
        }

        result = await service.soft_delete_property(
            pb=pb,
            token="token",
            user_id="user_1",
            record=record,
        )

        assert result.get("deleted_at") is not None
        pb.update_record.assert_called_once()
