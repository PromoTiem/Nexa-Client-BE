import pytest

from tests.helpers import get_live_token_or_skip


class TestMediaRoutes:
    async def test_list_media_without_auth_returns_401(self, live_client):
        response = await live_client.get("/media?site_id=s1")
        assert response.status_code == 401

    async def test_create_upload_url_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/media/upload-url",
            json={
                "site_id": "bad id!",
                "filename": "test.png",
                "content_type": "image/png",
                "size": 1024,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_create_upload_url_missing_required_returns_422(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/media/upload-url",
            json={"site_id": "s1"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_create_upload_url_without_auth_returns_401(self, live_client):
        response = await live_client.post(
            "/media/upload-url",
            json={
                "site_id": "s1",
                "filename": "test.png",
                "content_type": "image/png",
                "size": 1024,
            },
        )
        assert response.status_code == 401

    async def test_confirm_upload_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/media/bad id!/confirm",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_confirm_upload_without_auth_returns_401(self, live_client):
        response = await live_client.post("/media/f1/confirm")
        assert response.status_code == 401

    async def test_get_media_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.get(
            "/media/bad id!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_get_media_without_auth_returns_401(self, live_client):
        response = await live_client.get("/media/f1")
        assert response.status_code == 401

    async def test_update_media_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.patch(
            "/media/bad id!",
            json={"name": "Updated"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_update_media_without_auth_returns_401(self, live_client):
        response = await live_client.patch(
            "/media/f1",
            json={"name": "Updated"},
        )
        assert response.status_code == 401

    async def test_delete_media_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.delete(
            "/media/bad id!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_delete_media_without_auth_returns_401(self, live_client):
        response = await live_client.delete("/media/f1")
        assert response.status_code == 401

    async def test_bulk_delete_without_auth_returns_401(self, live_client):
        response = await live_client.post(
            "/media/bulk-delete",
            json={"file_ids": ["f1"]},
        )
        assert response.status_code == 401
