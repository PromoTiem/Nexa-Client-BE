from typing import Any

from fastapi import HTTPException


def enforce_account_access(record: dict[str, Any]) -> None:
    # Legacy records may omit status; explicit non-active states fail closed.
    if record.get("is_deleted") or record.get("status", "active") != "active":
        raise HTTPException(status_code=403, detail="Account is not active")
    if not record.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Client access requires tenant_id")
