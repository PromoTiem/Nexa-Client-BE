import httpx

from scripts.identity_rule_candidate import candidate
from tests.flows.test_transaction_flow import database  # noqa: F401


async def test_profile_rules_block_self_escalation_and_foreign_reads(database):  # noqa: F811
    base, admin, _ = database
    async with httpx.AsyncClient(
        base_url=base, headers={"Authorization": admin}
    ) as client:
        schema = (await client.get("/api/collections/users")).json()
        schema["fields"].extend(
            [
                {"name": name, "type": kind}
                for name, kind in (
                    ("tenant_id", "text"),
                    ("role", "text"),
                    ("status", "text"),
                    ("is_superuser", "bool"),
                    ("metadata", "json"),
                )
            ]
        )
        response = await client.patch("/api/collections/users", json=schema)
        response.raise_for_status()
        users = []
        for suffix in ("a", "b"):
            response = await client.post(
                "/api/collections/users/records",
                json={
                    "email": suffix + "@example.test",
                    "password": "Disposable-password-123",
                    "passwordConfirm": "Disposable-password-123",
                    "tenant_id": "tenant_" + suffix,
                    "role": "member",
                    "status": "active",
                },
            )
            response.raise_for_status()
            users.append(response.json())
        response = await client.post(
            "/api/collections/users/auth-with-password",
            json={
                "identity": "a@example.test",
                "password": "Disposable-password-123",
            },
        )
        response.raise_for_status()
        token = response.json()["token"]
        response = await client.patch("/api/collections/users", json=candidate(schema))
        assert response.is_success, response.text
        headers = {"Authorization": token}
        own = "/api/collections/users/records/" + users[0]["id"]
        for patch in (
            {"role": "owner"},
            {"tenant_id": "tenant_b"},
            {"is_superuser": True},
            {"status": "inactive"},
            {"verified": True},
        ):
            response = await client.patch(own, json=patch, headers=headers)
            assert response.status_code in (400, 403, 404), response.text
        response = await client.get(
            "/api/collections/users/records/" + users[1]["id"], headers=headers
        )
        assert response.status_code == 404
        response = await client.patch(own, json={"name": "Updated"}, headers=headers)
        assert response.status_code == 200, response.text
