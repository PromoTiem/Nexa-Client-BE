from copy import deepcopy

import pytest
from fastapi import HTTPException

from app.application.services.account_service import enforce_account_access
from app.interface.dto.user import UserUpdateRequest
from scripts.user_schema_parity import candidate


def test_additive_schema_preserves_pending_and_is_repeatable():
    original = {
        "name": "users",
        "type": "auth",
        "updateRule": "original",
        "fields": [
            {
                "id": "status_id",
                "name": "status",
                "type": "select",
                "maxSelect": 1,
                "values": ["active", "inactive", "pending"],
            }
        ],
    }
    before = deepcopy(original)
    result = candidate(original)
    assert original == before
    assert candidate(result) == result
    assert result["updateRule"] == "original"
    assert result["fields"][0]["id"] == "status_id"
    assert result["fields"][0]["values"] == [
        "active",
        "inactive",
        "pending",
        "suspended",
    ]
    assert result["fields"][1] == {
        "name": "is_deleted",
        "type": "bool",
        "required": False,
    }


@pytest.mark.parametrize("status", ["pending", "suspended", "inactive"])
def test_known_nonactive_status_roundtrips_but_cannot_authenticate(status):
    assert UserUpdateRequest(status=status).status == status
    with pytest.raises(HTTPException) as error:
        enforce_account_access({"tenant_id": "tenant", "status": status})
    assert error.value.status_code == 403


def test_unknown_status_schema_fails_closed():
    with pytest.raises(ValueError):
        candidate(
            {
                "name": "users",
                "type": "auth",
                "fields": [{"name": "status", "type": "select", "values": ["custom"]}],
            }
        )
