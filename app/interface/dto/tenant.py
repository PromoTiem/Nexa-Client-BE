from typing import Any, Dict, Optional

from pydantic import BaseModel


class TenantResponse(BaseModel):
    id: str
    tenant_id: str
    name: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created: Optional[str] = None
    updated: Optional[str] = None
