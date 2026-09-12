from typing import Any

from pydantic import BaseModel


class TenantResponse(BaseModel):
    id: str
    tenant_id: str
    name: str | None = None
    plan: str | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None
    default: bool | None = False
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
