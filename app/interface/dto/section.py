from pydantic import BaseModel

from app.interface.dto.common import PaginatedResponse


class SectionResponse(BaseModel):
    id: str
    section_id: str
    name: str
    layout: str | None = None
    order_index: int | None = None
    block_ids: list[str] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


SectionListResponse = PaginatedResponse[SectionResponse]
