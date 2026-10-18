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
                    ("is_deleted", "bool"),
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

        # A tenant owner can still administer lower-role accounts via the
        # server-mediated gateway while direct collection creation is locked.
        from app.application.access import AuthContext
        from app.application.services.account_gateway import AccountGateway
        from app.infrastructure.pocketbase.client import PocketBaseClient

        response = await client.patch(own, json={"role": "owner"})
        response.raise_for_status()
        gateway = AccountGateway(
            PocketBaseClient(base, static_token=admin, max_retries=1),
            AuthContext(token, {**users[0], "role": "owner"}),
        )
        created = await gateway.create_record(
            "users",
            {
                "email": "managed@example.test",
                "password": "Managed-password-123",
                "passwordConfirm": "Managed-password-123",
                "name": "Managed",
                "tenant_id": "tenant_a",
                "role": "member",
                "status": "active",
                "first_auth": True,
                "metadata": {},
            },
            token=token,
        )
        assert created["tenant_id"] == "tenant_a"
        updated = await gateway.update_record(
            "users", created["id"], {"status": "inactive"}, token=token
        )
        assert updated["status"] == "inactive"
        denied = await client.post(
            "/api/collections/users/records",
            headers=headers,
            json={
                "email": "direct@example.test",
                "password": "Managed-password-123",
                "passwordConfirm": "Managed-password-123",
                "tenant_id": "tenant_a",
                "role": "owner",
            },
        )
        assert denied.status_code in (400, 403)

        # Reapplying identical rules is idempotent and keeps self-service intact.
        response = await client.patch("/api/collections/users", json=candidate(schema))
        assert response.is_success, response.text
        response = await client.patch(
            own, json={"metadata": {"locale": "vi", "role": "owner"}}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["role"] == "owner"  # real role was set by admin above
        response = await client.post(
            "/api/collections/users/auth-refresh", headers=headers
        )
        assert response.status_code == 200, response.text
        response = await client.patch(
            own,
            headers=headers,
            json={
                "oldPassword": "Disposable-password-123",
                "password": "New-password-456",
                "passwordConfirm": "New-password-456",
            },
        )
        assert response.status_code == 200, response.text
        old = await client.post(
            "/api/collections/users/auth-with-password",
            json={
                "identity": "a@example.test",
                "password": "Disposable-password-123",
            },
        )
        assert old.status_code == 400
        new = await client.post(
            "/api/collections/users/auth-with-password",
            json={
                "identity": "a@example.test",
                "password": "New-password-456",
            },
        )
        assert new.status_code == 200, new.text
        # Schema rollback restores the original rules and preserves user data.
        response = await client.patch("/api/collections/users", json=schema)
        assert response.is_success, response.text
        restored = (await client.get("/api/collections/users")).json()
        for field in (
            "listRule",
            "viewRule",
            "createRule",
            "updateRule",
            "deleteRule",
            "manageRule",
        ):
            assert restored.get(field) == schema.get(field)
        persisted = (await client.get(own)).json()
        assert persisted["metadata"]["locale"] == "vi"
