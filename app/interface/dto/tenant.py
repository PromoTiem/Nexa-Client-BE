from typing import Any, Dict, Optional

from pydantic import BaseModel


class TenantResponse(BaseModel):
    id: str
    tenant_id: str
    name: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    default: Optional[bool] = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
