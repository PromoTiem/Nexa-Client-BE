import pytest

from tests.helpers import get_live_token_or_skip


class TestAuthRoutes:
    async def test_login_without_auth_returns_422(self, live_client):
        response = await live_client.post("/auth/login", json={})
        assert response.status_code == 422

    async def test_login_missing_fields_returns_422(self, live_client):
        response = await live_client.post(
            "/auth/login", json={"identity": "test@example.com"}
        )
        assert response.status_code == 422

    async def test_refresh_without_token_returns_401(self, live_client):
        response = await live_client.post("/auth/refresh")
        assert response.status_code == 401

    async def test_login_invalid_credentials_returns_401(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/auth/login",
            json={
                "identity": "nonexistent@example.com",
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 401

    async def test_login_success_returns_token(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        from app.config import get_settings

        settings = get_settings()

        response = await live_client.post(
            "/auth/login",
            json={
                "identity": settings.test_identity,
                "password": settings.test_password,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "record" in data

    async def test_refresh_with_valid_token_returns_200(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
