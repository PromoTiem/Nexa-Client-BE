import pytest

from tests.helpers import get_live_token_or_skip


class TestPropertyRoutes:
    async def test_list_properties_without_auth_returns_401(self, live_client):
        response = await live_client.get("/sites/s1/properties")
        assert response.status_code == 401

    async def test_create_property_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/sites/bad id!/properties",
            json={
                "property_id": "p1",
                "name": "Test",
                "type": "product",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_create_property_missing_required_returns_422(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/sites/s1/properties",
            json={"property_id": "p1"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_create_property_without_auth_returns_401(self, live_client):
        response = await live_client.post(
            "/sites/s1/properties",
            json={
                "property_id": "p1",
                "name": "Test",
                "type": "product",
            },
        )
        assert response.status_code == 401

    async def test_get_property_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.get(
            "/properties/bad id!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_get_property_without_auth_returns_401(self, live_client):
        response = await live_client.get("/properties/p1")
        assert response.status_code == 401

    async def test_update_property_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.patch(
            "/properties/bad id!",
            json={"name": "Updated"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_update_property_without_auth_returns_401(self, live_client):
        response = await live_client.patch(
            "/properties/p1",
            json={"name": "Updated"},
        )
        assert response.status_code == 401

    async def test_delete_property_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.delete(
            "/properties/bad id!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_delete_property_without_auth_returns_401(self, live_client):
        response = await live_client.delete("/properties/p1")
        assert response.status_code == 401
