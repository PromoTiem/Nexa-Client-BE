import httpx

from scripts.user_schema_parity import candidate
from tests.flows.test_transaction_flow import database  # noqa: F401


async def test_schema_upgrade_preserves_pending_records_and_rule_rollback(database):  # noqa: F811
    base, token, _ = database
    async with httpx.AsyncClient(
        base_url=base, headers={"Authorization": token}
    ) as api:
        original = (await api.get("/api/collections/users")).json()
        original["fields"].append(
            {
                "name": "status",
                "type": "select",
                "maxSelect": 1,
                "values": ["active", "inactive", "pending"],
            }
        )
        response = await api.patch("/api/collections/users", json=original)
        response.raise_for_status()
        before = (await api.get("/api/collections/users")).json()
        response = await api.post(
            "/api/collections/users/records",
            json={
                "email": "pending@example.test",
                "password": "Disposable-password-123",
                "passwordConfirm": "Disposable-password-123",
                "status": "pending",
            },
        )
        response.raise_for_status()
        record_id = response.json()["id"]
        for _ in range(2):
            current = (await api.get("/api/collections/users")).json()
            response = await api.patch(
                "/api/collections/users", json=candidate(current)
            )
            assert response.is_success, response.text
        record = (await api.get("/api/collections/users/records/" + record_id)).json()
        assert record["status"] == "pending" and record["is_deleted"] is False
        response = await api.patch(
            "/api/collections/users/records/" + record_id,
            json={"status": "suspended", "is_deleted": True},
        )
        response.raise_for_status()
        # Roll back access rules only: dropping new fields/status values would
        # destroy data written by the upgraded application.
        rules = {
            key: before.get(key)
            for key in (
                "listRule",
                "viewRule",
                "createRule",
                "updateRule",
                "deleteRule",
                "manageRule",
            )
        }
        response = await api.patch("/api/collections/users", json=rules)
        response.raise_for_status()
        record = (await api.get("/api/collections/users/records/" + record_id)).json()
        assert record["status"] == "suspended" and record["is_deleted"] is True
