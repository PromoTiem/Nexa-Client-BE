from typing import Any

from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class BlockResponse(BaseModel):
    id: str
    block_id: str
    name: str
    type: str
    order_index: int | None = None
    props: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


BlockListResponse = PaginatedResponse[BlockResponse]
