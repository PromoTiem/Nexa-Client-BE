import pytest

from tests.helpers import get_live_token_or_skip


class TestSitesRoute:
    async def test_list_sites_without_auth_returns_401(self, live_client):
        response = await live_client.get("/sites")
        assert response.status_code == 401

    async def test_create_site_without_auth_returns_401(self, live_client):
        response = await live_client.post(
            "/sites",
            json={
                "site_id": "s1",
                "tenant_id": "t1",
                "template_id": "tpl1",
                "domain": "a.com",
            },
        )
        assert response.status_code == 401

    async def test_create_site_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/sites",
            json={
                "site_id": "bad id!",
                "tenant_id": "tenant_abc",
                "template_id": "tpl_abc",
                "domain": "a.com",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 403)

    async def test_create_site_missing_required_returns_422(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.post(
            "/sites",
            json={"site_id": "s1"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (422, 403)

    async def test_get_site_without_auth_returns_401(self, live_client):
        response = await live_client.get("/sites/some_site")
        assert response.status_code == 401

    async def test_get_site_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.get(
            "/sites/bad id!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 403)

    async def test_update_site_without_auth_returns_401(self, live_client):
        response = await live_client.patch(
            "/sites/some_site",
            json={"domain": "x.com"},
        )
        assert response.status_code == 401

    async def test_delete_site_without_auth_returns_401(self, live_client):
        response = await live_client.delete("/sites/some_site")
        assert response.status_code == 401

    async def test_delete_site_invalid_id_returns_400(self, live_client):
        token = await get_live_token_or_skip()
        if not token:
            pytest.skip("No test credentials")

        response = await live_client.delete(
            "/sites/bad id!",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 403)
