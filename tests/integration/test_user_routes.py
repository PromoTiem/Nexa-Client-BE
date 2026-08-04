import pytest

from tests.helpers import get_live_token_or_skip


class TestUserRoutes:
    async def test_get_my_profile_without_auth_returns_401(self, live_client):
        response = await live_client.get("/users/me")
        assert response.status_code == 401

    async def test_update_my_profile_without_auth_returns_401(self, live_client):
        response = await live_client.patch(
            "/users/me",
            json={"name": "Updated"},
        )
        assert response.status_code == 401

    async def test_list_users_without_auth_returns_401(self, live_client):
        response = await live_client.get("/users")
        assert response.status_code == 401

    async def test_create_user_without_auth_returns_401(self, live_client):
        response = await live_client.post(
            "/users",
            json={"email": "new@example.com"},
        )
        assert response.status_code == 401

    async def test_get_user_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.get(
            "/users/bad id!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 403)

    async def test_get_user_without_auth_returns_401(self, live_client):
        response = await live_client.get("/users/u1")
        assert response.status_code == 401

    async def test_update_user_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.patch(
            "/users/bad id!",
            json={"name": "Updated"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 403)

    async def test_update_user_without_auth_returns_401(self, live_client):
        response = await live_client.patch(
            "/users/u1",
            json={"name": "Updated"},
        )
        assert response.status_code == 401

    async def test_delete_user_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.delete(
            "/users/bad id!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 403)

    async def test_delete_user_without_auth_returns_401(self, live_client):
        response = await live_client.delete("/users/u1")
        assert response.status_code == 401

    async def test_create_user_missing_email_returns_422(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/users",
            json={"name": "Test User"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (422, 403)
