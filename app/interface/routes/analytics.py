from fastapi import APIRouter, Depends, Query

from app.application.services.analytics_service import AnalyticsService
from app.infrastructure.analytics.aggregator import AnalyticsAggregator
from app.infrastructure.analytics.collector import AnalyticsCollector
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_analytics_collector,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.dto.analytics import (
    AggregateRequest,
    AggregateResponse,
    AnalyticsBatchRequest,
    AnalyticsEventRequest,
    BatchTrackResponse,
    DashboardResponse,
    EventTrackResponse,
    KPISummary,
    ProductAnalyticsResponse,
    TopItem,
    TopProductItem,
    TopProductsResponse,
    TrendBreakdownItem,
    TrendDataPoint,
    TrendResponse,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import validate_id

logger = get_logger("analytics_routes")

router = APIRouter()


def _build_analytics_service(
    collector: AnalyticsCollector,
    pb: PocketBaseClient,
    token: str | None = None,
) -> AnalyticsService:
    aggregator = AnalyticsAggregator(pb, token=token)
    return AnalyticsService(
        collector=collector, aggregator=aggregator, pb=pb, token=token
    )


COLLECTION_PROPERTIES = "properties"


async def _resolve_property_names(
    pb: PocketBaseClient,
    site_id: str,
    property_ids: list[str],
    token: str | None = None,
) -> dict[str, str]:
    """Batch-fetch property names for a list of property_ids. Returns {property_id: name}."""
    if not property_ids:
        return {}
    or_filter = " || ".join(f'property_id="{pid}"' for pid in property_ids)
    filter_expr = f'site_id="{site_id}" && ({or_filter}) && deleted_at=""'
    try:
        result = await pb.list_records(
            COLLECTION_PROPERTIES,
            token=token,
            filter=filter_expr,
            per_page=500,
        )
        return {
            item["property_id"]: item.get("name", item["property_id"])
            for item in result.get("items", [])
        }
    except Exception:
        return {pid: pid for pid in property_ids}


# --- Event Tracking ---


@router.post(
    "/analytics/events",
    response_model=BatchTrackResponse,
    status_code=201,
)
async def track_events_batch(
    body: AnalyticsBatchRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    collector: AnalyticsCollector = Depends(get_analytics_collector),
) -> BatchTrackResponse:
    enforce_permission(ctx.auth, Permission.ANALYTICS_TRACK)
    service = _build_analytics_service(collector, pb, ctx.token)

    events = []
    for ev in body.events:
        validate_id(ev.site_id, "site_id")
        events.append(
            {
                "event_type": ev.event_type,
                "site_id": ev.site_id,
                "property_id": ev.property_id,
                "tenant_id": ctx.tenant_id or "",
                "session_id": ev.session_id,
                "metadata": ev.metadata,
                "user_agent": ev.user_agent,
                "timestamp": ev.timestamp,
            }
        )

    result = await service.track_batch(events)
    return BatchTrackResponse(**result)


@router.post(
    "/analytics/events/track",
    response_model=EventTrackResponse,
    status_code=201,
)
async def track_event(
    body: AnalyticsEventRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    collector: AnalyticsCollector = Depends(get_analytics_collector),
) -> EventTrackResponse:
    enforce_permission(ctx.auth, Permission.ANALYTICS_TRACK)
    validate_id(body.site_id, "site_id")
    service = _build_analytics_service(collector, pb, ctx.token)

    event_id = await service.track_event(
        event_type=body.event_type,
        site_id=body.site_id,
        property_id=body.property_id,
        tenant_id=ctx.tenant_id or "",
        session_id=body.session_id,
        metadata=body.metadata,
        user_agent=body.user_agent,
        timestamp=body.timestamp,
    )
    return EventTrackResponse(event_id=event_id, accepted=True)


# --- Dashboard Data ---


@router.get(
    "/analytics/dashboard/{site_id}",
    response_model=DashboardResponse,
)
async def get_dashboard(
    site_id: str,
    range: str = Query("30d", pattern="^(7d|30d|90d|1y|all)$"),
    property_id: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    collector: AnalyticsCollector = Depends(get_analytics_collector),
) -> DashboardResponse:
    enforce_permission(ctx.auth, Permission.ANALYTICS_VIEW)
    validate_id(site_id, "site_id")
    service = _build_analytics_service(collector, pb, ctx.token)

    from datetime import UTC, datetime

    start, end = service._date_range(range)
    now = datetime.now(UTC).isoformat()

    kpis_dict = await service.get_kpis(site_id, start, end, property_id=property_id)
    kpis = KPISummary(**kpis_dict)

    kpis_change = await service.get_kpis_change(site_id, range)

    top_raw = await service.get_top_properties(site_id, "views", start, end, limit=5)
    prop_ids = [t["property_id"] for t in top_raw if t.get("property_id")]
    name_map = await _resolve_property_names(pb, site_id, prop_ids, ctx.token)
    top_services = [
        TopItem(
            property_id=t["property_id"],
            name=name_map.get(t["property_id"], t["property_id"]),
            views=t.get("views", 0),
            bookings=t.get("bookings", 0),
            revenue=t.get("revenue", 0.0),
        )
        for t in top_raw
    ]

    return DashboardResponse(
        site_id=site_id,
        period=range,
        date_from=start,
        date_to=end,
        kpis=kpis,
        kpis_change=kpis_change,
        top_services=top_services,
        generated_at=now,
    )


@router.get(
    "/analytics/trends/{site_id}",
    response_model=TrendResponse,
)
async def get_trends(
    site_id: str,
    range: str = Query("30d"),
    metric: str = Query("views_trend"),
    period: str = Query("daily"),
    property_id: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    collector: AnalyticsCollector = Depends(get_analytics_collector),
) -> TrendResponse:
    enforce_permission(ctx.auth, Permission.ANALYTICS_VIEW)
    validate_id(site_id, "site_id")
    service = _build_analytics_service(collector, pb, ctx.token)

    from datetime import UTC, datetime

    start, end = service._date_range(range)
    now = datetime.now(UTC).isoformat()

    breakdown_metrics = {
        "service_breakdown",
        "product_breakdown",
        "traffic_sources",
        "device_breakdown",
    }
    if metric in breakdown_metrics:
        raw = await service.get_breakdown(site_id, metric, start, end)
        data = [TrendBreakdownItem(**item) for item in raw]
    else:
        raw = await service.get_trend(
            site_id, metric, start, end, property_id=property_id
        )
        data = [TrendDataPoint(**item) for item in raw]

    return TrendResponse(
        site_id=site_id,
        metric=metric,
        period=period,
        range=range,
        data=data,
        generated_at=now,
    )


@router.get(
    "/analytics/top-products/{site_id}",
    response_model=TopProductsResponse,
)
async def get_top_products(
    site_id: str,
    range: str = Query("30d"),
    metric: str = Query("views"),
    limit: int = Query(10, ge=1, le=50),
    type: str | None = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    collector: AnalyticsCollector = Depends(get_analytics_collector),
) -> TopProductsResponse:
    enforce_permission(ctx.auth, Permission.ANALYTICS_VIEW)
    validate_id(site_id, "site_id")
    service = _build_analytics_service(collector, pb, ctx.token)

    from datetime import UTC, datetime

    start, end = service._date_range(range)
    now = datetime.now(UTC).isoformat()

    raw = await service.get_top_properties(site_id, metric, start, end, limit=limit)

    prop_ids = [t["property_id"] for t in raw if t.get("property_id")]
    name_map = await _resolve_property_names(pb, site_id, prop_ids, ctx.token)

    items = [
        TopProductItem(
            property_id=t["property_id"],
            name=name_map.get(t["property_id"], t["property_id"]),
            views=t.get("views", 0),
            bookings=t.get("bookings", 0),
            revenue=t.get("revenue", 0.0),
        )
        for t in raw
    ]

    return TopProductsResponse(
        site_id=site_id,
        period=range,
        sorted_by=metric,
        items=items,
        generated_at=now,
    )


@router.get(
    "/analytics/product/{site_id}/{property_id}",
    response_model=ProductAnalyticsResponse,
)
async def get_product_analytics(
    site_id: str,
    property_id: str,
    range: str = Query("30d"),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    collector: AnalyticsCollector = Depends(get_analytics_collector),
) -> ProductAnalyticsResponse:
    enforce_permission(ctx.auth, Permission.ANALYTICS_VIEW)
    validate_id(site_id, "site_id")
    validate_id(property_id, "property_id")
    service = _build_analytics_service(collector, pb, ctx.token)

    from datetime import UTC, datetime

    start, end = service._date_range(range)
    now = datetime.now(UTC).isoformat()

    kpis_dict = await service.get_kpis(site_id, start, end, property_id=property_id)
    kpis = KPISummary(**kpis_dict)

    trend_raw = await service.get_trend(
        site_id, "views_trend", start, end, property_id=property_id
    )
    views_trend = [TrendDataPoint(**item) for item in trend_raw]

    name_map = await _resolve_property_names(pb, site_id, [property_id], ctx.token)

    return ProductAnalyticsResponse(
        site_id=site_id,
        property_id=property_id,
        name=name_map.get(property_id, property_id),
        period=range,
        kpis=kpis,
        views_trend=views_trend,
        generated_at=now,
    )


# --- Aggregation ---


@router.post(
    "/analytics/aggregate/{site_id}",
    response_model=AggregateResponse,
    status_code=200,
)
async def aggregate_analytics(
    site_id: str,
    body: AggregateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    collector: AnalyticsCollector = Depends(get_analytics_collector),
) -> AggregateResponse:
    enforce_permission(ctx.auth, Permission.ANALYTICS_TRACK)
    validate_id(site_id, "site_id")
    service = _build_analytics_service(collector, pb, ctx.token)

    result = await service.aggregate_date_range(site_id, body.start_date, body.end_date)
    return AggregateResponse(**result)
