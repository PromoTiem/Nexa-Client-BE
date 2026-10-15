import httpx

from app.application.access import AuthContext
from app.application.services.site_gateway import SiteGateway
from app.infrastructure.pocketbase.client import PocketBaseClient
from scripts.identity_rule_candidate import candidate
from tests.flows.test_transaction_flow import database  # noqa: F401


async def test_site_rules_gateway_and_rollback(database):  # noqa: F811
    base, admin, _ = database
    async with httpx.AsyncClient(
        base_url=base, headers={"Authorization": admin}
    ) as api:

        async def post(path, data):
            response = await api.post(path, json=data)
            response.raise_for_status()
            return response.json()

        tenant_schema = (await api.get("/api/collections/tenants")).json()
        schema = (await api.get("/api/collections/sites")).json()
        for field in schema["fields"]:
            if field["name"] == "tenant_id":
                field.clear()
                field.update(
                    name="tenant_id",
                    type="relation",
                    collectionId=tenant_schema["id"],
                    maxSelect=1,
                )
        response = await api.patch("/api/collections/sites", json=schema)
        response.raise_for_status()
        original = (await api.get("/api/collections/sites")).json()
        response = await api.patch(
            "/api/collections/users",
            json={
                "fields": [
                    {"name": "tenant_id", "type": "text"},
                    {"name": "role", "type": "text"},
                    {"name": "status", "type": "text"},
                ]
            },
        )
        response.raise_for_status()
        tenant = await post(
            "/api/collections/tenants/records", {"tenant_id": "tenant_a"}
        )
        user = await post(
            "/api/collections/users/records",
            {
                "email": "site@example.test",
                "password": "Disposable-password-123",
                "passwordConfirm": "Disposable-password-123",
                "tenant_id": "tenant_a",
                "role": "owner",
                "status": "active",
            },
        )
        auth = await post(
            "/api/collections/users/auth-with-password",
            {"identity": "site@example.test", "password": "Disposable-password-123"},
        )
        token = auth["token"]
        for _ in range(2):
            response = await api.patch(
                "/api/collections/sites", json=candidate(original)
            )
            assert response.is_success, response.text
        server = PocketBaseClient(base, static_token=admin, max_retries=1)
        caller = PocketBaseClient(base, max_retries=1)
        context = AuthContext(token, user)
        gateway = SiteGateway(caller, server, context, "create")
        site = await gateway.create_record(
            "sites", {"site_id": "site_test", "tenant_id": tenant["id"], "config": {}}
        )
        response = await api.post(
            "/api/collections/sites/records",
            headers={"Authorization": token},
            json={"site_id": "forged", "tenant_id": tenant["id"]},
        )
        assert response.status_code in (400, 403)
        updated = await SiteGateway(caller, server, context, "update").update_record(
            "sites", site["id"], {"config": {"name": "Saved"}}
        )
        assert updated["config"]["name"] == "Saved"
        response = await api.get(
            "/api/collections/sites/records/" + site["id"],
            headers={"Authorization": token},
        )
        assert response.status_code == 200
        await SiteGateway(caller, server, context, "delete").update_record(
            "sites", site["id"], {"config": {"_nexa_lifecycle": {"deleted_at": "now"}}}
        )
        response = await api.get(
            "/api/collections/sites/records/" + site["id"],
            headers={"Authorization": token},
        )
        assert response.status_code == 404
        response = await api.patch("/api/collections/sites", json=original)
        response.raise_for_status()
        restored = (await api.get("/api/collections/sites")).json()
        for field in ("listRule", "viewRule", "createRule", "updateRule", "deleteRule"):
            assert restored[field] == original[field]
        persisted = (
            await api.get("/api/collections/sites/records/" + site["id"])
        ).json()
        assert persisted["config"]["_nexa_lifecycle"]["deleted_at"] == "now"
