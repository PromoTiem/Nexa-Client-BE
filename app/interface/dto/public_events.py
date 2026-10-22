import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Events a public page may report. Purchases are recorded server-side only:
# a browser can't be trusted with revenue.
PublicEventType = Literal[
    "page_view",
    "product_view",
    "product_impression",
    "add_to_cart",
    "remove_from_cart",
    "checkout_start",
    "search",
    "session_start",
    "session_end",
]

# Same ceiling the public booking form already applies to its payload.
MAX_METADATA_BYTES = 16384


class PublicAnalyticsEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    event_type: PublicEventType
    property_id: str | None = Field(
        default=None, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    session_id: str = Field(default="", max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _small_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value).encode()) > MAX_METADATA_BYTES:
            raise ValueError("metadata too large")
        return value


class PublicEventAccepted(BaseModel):
    accepted: bool = True


class PublicSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
