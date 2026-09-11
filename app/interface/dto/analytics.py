from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Event Tracking ---


class AnalyticsEventRequest(BaseModel):
    event_type: str
    site_id: str
    property_id: str | None = None
    session_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    user_agent: str = ""
    timestamp: str | None = None


class AnalyticsBatchRequest(BaseModel):
    events: list[AnalyticsEventRequest] = Field(max_length=100)


class EventTrackResponse(BaseModel):
    event_id: str
    accepted: bool


class BatchTrackResponse(BaseModel):
    accepted: int
    rejected: int
    errors: list[str] = Field(default_factory=list)


# --- Dashboard ---


class KPISummary(BaseModel):
    total_views: int = 0
    unique_visitors: int = 0
    product_views: int = 0
    bookings: int = 0
    orders: int = 0
    revenue: float = 0.0
    conversion_rate: float = 0.0
    avg_order_value: float = 0.0
    search_count: int = 0


class TopItem(BaseModel):
    property_id: str
    name: str
    views: int = 0
    bookings: int = 0
    revenue: float = 0.0


class DashboardResponse(BaseModel):
    site_id: str
    period: str
    date_from: str
    date_to: str
    kpis: KPISummary
    kpis_change: dict[str, float] = Field(default_factory=dict)
    top_services: list[TopItem] = Field(default_factory=list)
    generated_at: str


# --- Trends ---


class TrendDataPoint(BaseModel):
    date: str
    value: float


class TrendBreakdownItem(BaseModel):
    label: str
    value: float
    property_id: str | None = None


class TrendResponse(BaseModel):
    site_id: str
    metric: str
    period: str
    range: str
    data: list[TrendDataPoint | TrendBreakdownItem] = Field(default_factory=list)
    generated_at: str


# --- Top Products ---


class TopProductItem(BaseModel):
    property_id: str
    name: str
    type: str | None = None
    views: int = 0
    unique_visitors: int = 0
    bookings: int = 0
    revenue: float = 0.0
    conversion_rate: float = 0.0


class TopProductsResponse(BaseModel):
    site_id: str
    period: str
    sorted_by: str
    items: list[TopProductItem] = Field(default_factory=list)
    generated_at: str


# --- Product Analytics ---


class ProductAnalyticsResponse(BaseModel):
    site_id: str
    property_id: str
    name: str
    period: str
    kpis: KPISummary
    views_trend: list[TrendDataPoint] = Field(default_factory=list)
    generated_at: str
