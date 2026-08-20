from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class BlockResponse(BaseModel):
    id: str
    block_id: str
    name: str
    type: str
    order_index: Optional[int] = None
    props: Optional[Dict[str, Any]] = None
    style: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


BlockListResponse = PaginatedResponse[BlockResponse]
