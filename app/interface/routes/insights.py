import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.application.services.insight_service import InsightService
from app.config import Settings, get_settings
from app.infrastructure.llm.cache import LLMCache
from app.infrastructure.llm.client import LLMClient
from app.infrastructure.llm.token_tracker import TokenTracker
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.interface.dependencies import (
    TenantContext,
    get_pocketbase_client,
    get_tenant_context,
)
from app.interface.dto.insights import (
    AnalyzeRequest,
    BatchAnalysisRequest,
    BatchAnalysisStatusResponse,
    ContentOptimizationResponse,
    LLMHealthResponse,
    QualityScoreResponse,
    RecommendationsResponse,
    SEOAnalysisResponse,
    SiteSummaryResponse,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import validate_id

logger = get_logger("insight_routes")

router = APIRouter()


def _get_insight_service(
    ctx: TenantContext = Depends(get_tenant_context),
    settings: Settings = Depends(get_settings),
) -> InsightService:
    from app.infrastructure.pocketbase.client import PocketBaseClient

    pb = PocketBaseClient(
        base_url=settings.pocketbase_url,
        static_token=ctx.token,
        timeout=settings.pocketbase_timeout,
        max_retries=settings.pocketbase_max_retries,
        retry_backoff=settings.pocketbase_retry_backoff,
    )
    llm = LLMClient(settings.llm)
    return InsightService(pb=pb, llm=llm)


# --- Analyze ---


@router.post(
    "/insights/analyze/{site_id}/{property_id}",
    response_model=dict,
)
async def analyze_property(
    site_id: str,
    property_id: str,
    body: AnalyzeRequest | None = None,
    ctx: TenantContext = Depends(get_tenant_context),
    service: InsightService = Depends(_get_insight_service),
) -> dict:
    enforce_permission(ctx.auth, Permission.INSIGHTS_ACCESS)
    validate_id(site_id, "site_id")
    validate_id(property_id, "property_id")

    force = body.force if body else False
    insight_type = body.type if body else "all"

    result = await service.analyze_property(
        site_id=site_id,
        property_id=property_id,
        force=force,
        insight_type=insight_type,
        tenant_id=ctx.tenant_id or "",
    )
    return result


@router.post(
    "/insights/batch-analyze/{site_id}",
    response_model=BatchAnalysisStatusResponse,
    status_code=202,
)
async def batch_analyze(
    site_id: str,
    body: BatchAnalysisRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    service: InsightService = Depends(_get_insight_service),
) -> BatchAnalysisStatusResponse:
    enforce_permission(ctx.auth, Permission.INSIGHTS_ACCESS)
    validate_id(site_id, "site_id")

    # Count properties
    props_result = await service._pb.list_records(
        "properties",
        filter=f'site_id="{site_id}"',
        per_page=1,
    )
    total = props_result.get("totalItems", 0)

    return BatchAnalysisStatusResponse(
        site_id=site_id,
        job_id=f"job_{uuid.uuid4().hex[:8]}",
        total_products=total,
        queued=total,
        status="queued",
        estimated_tokens=total * 1250,
        estimated_cost_usd=round(total * 0.0002, 4),
    )


@router.get(
    "/insights/score/{site_id}/{property_id}",
    response_model=QualityScoreResponse,
)
async def get_score(
    site_id: str,
    property_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    service: InsightService = Depends(_get_insight_service),
) -> QualityScoreResponse:
    enforce_permission(ctx.auth, Permission.INSIGHTS_ACCESS)
    validate_id(site_id, "site_id")
    validate_id(property_id, "property_id")

    result = await service.get_score(site_id, property_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Insight not found. Run POST /insights/analyze first.")

    return QualityScoreResponse(
        property_id=property_id,
        score=result.get("overall_score", 0),
        breakdown=result.get("breakdown", {}),
        recommendations=result.get("recommendations", []),
        analyzed_at=result.get("analyzed_at", ""),
        expires_at=result.get("expires_at"),
    )


@router.get(
    "/insights/seo/{site_id}/{property_id}",
    response_model=SEOAnalysisResponse,
)
async def get_seo(
    site_id: str,
    property_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    service: InsightService = Depends(_get_insight_service),
) -> SEOAnalysisResponse:
    enforce_permission(ctx.auth, Permission.INSIGHTS_ACCESS)
    validate_id(site_id, "site_id")
    validate_id(property_id, "property_id")

    result = await service.get_seo(site_id, property_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Insight not found. Run POST /insights/analyze first.")

    return SEOAnalysisResponse(
        property_id=property_id,
        title_score=result.get("title_score", 0),
        meta_description_score=result.get("meta_description_score", 0),
        slug_score=result.get("slug_score", 0),
        keyword_suggestions=result.get("keyword_suggestions", []),
        issues=result.get("issues", []),
        analyzed_at=result.get("analyzed_at", ""),
    )


@router.get(
    "/insights/recommendations/{site_id}",
    response_model=RecommendationsResponse,
)
async def get_recommendations(
    site_id: str,
    type: str = Query("all"),
    priority: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
    service: InsightService = Depends(_get_insight_service),
) -> RecommendationsResponse:
    enforce_permission(ctx.auth, Permission.INSIGHTS_ACCESS)
    validate_id(site_id, "site_id")

    recs = await service.get_recommendations(site_id)

    # Filter by priority if specified
    if priority:
        recs = [r for r in recs if r.get("severity") == priority]

    recs = recs[:limit]

    by_priority: dict[str, int] = {}
    for r in recs:
        sev = r.get("severity", "info")
        by_priority[sev] = by_priority.get(sev, 0) + 1

    from datetime import UTC, datetime

    return RecommendationsResponse(
        site_id=site_id,
        total_recommendations=len(recs),
        by_priority=by_priority,
        recommendations=recs,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/insights/summary/{site_id}",
    response_model=SiteSummaryResponse,
)
async def get_site_summary(
    site_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    service: InsightService = Depends(_get_insight_service),
) -> SiteSummaryResponse:
    enforce_permission(ctx.auth, Permission.INSIGHTS_ACCESS)
    validate_id(site_id, "site_id")

    result = await service.get_site_summary(site_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="AI summary unavailable")

    return SiteSummaryResponse(**result)


@router.get(
    "/insights/health",
    response_model=LLMHealthResponse,
)
async def get_llm_health(
    ctx: TenantContext = Depends(get_tenant_context),
    service: InsightService = Depends(_get_insight_service),
) -> LLMHealthResponse:
    enforce_permission(ctx.auth, Permission.INSIGHTS_ACCESS)

    result = await service.get_llm_health()
    return LLMHealthResponse(**result)
