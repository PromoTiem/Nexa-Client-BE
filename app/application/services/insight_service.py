import uuid
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.llm.client import LLMClient
from app.infrastructure.llm.prompts import (
    PRODUCT_OPTIMIZATION_SYSTEM,
    PRODUCT_OPTIMIZATION_USER,
    SEO_ANALYSIS_SYSTEM,
    SEO_ANALYSIS_USER,
    QUALITY_SCORING_SYSTEM,
    QUALITY_SCORING_USER,
    SITE_SUMMARY_SYSTEM,
    SITE_SUMMARY_USER,
    format_product_fields,
)
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient

logger = get_logger("insight.service")

COLLECTION_INSIGHTS = "analytics_insights"
COLLECTION_PROPERTIES = "properties"


class InsightService:
    """AI-powered analysis of product data."""

    def __init__(self, pb: PocketBaseClient, llm: LLMClient) -> None:
        self._pb = pb
        self._llm = llm

    async def analyze_property(
        self,
        site_id: str,
        property_id: str,
        *,
        force: bool = False,
        insight_type: str = "all",
        tenant_id: str = "",
    ) -> dict[str, Any]:
        """Run AI analysis on a property. Returns cached result if available."""
        now = datetime.now(UTC).isoformat()

        # Fetch property
        prop = await self._pb.find_record_by_filter(
            COLLECTION_PROPERTIES,
            f'property_id="{property_id}" && site_id="{site_id}"',
        )

        fields_data = format_product_fields([prop])
        results: dict[str, Any] = {}

        types_to_run = (
            ["quality_score", "seo_analysis", "content_optimization"]
            if insight_type == "all"
            else [insight_type]
        )

        for itype in types_to_run:
            # Check cache unless forced
            if not force:
                cached = await self._get_cached_insight(site_id, property_id, itype)
                if cached:
                    results[itype] = cached
                    continue

            # Generate insight
            insight = await self._generate_insight(itype, fields_data, prop)
            results[itype] = insight

            # Cache
            await self._cache_insight(
                site_id=site_id,
                property_id=property_id,
                tenant_id=tenant_id,
                insight_type=itype,
                content=insight,
                score=insight.get("overall_score") or insight.get("score"),
            )

        return {
            "property_id": property_id,
            "analyses": results,
            "model_used": self._llm._settings.model,
            "tokens_used": 0,
            "cached": False,
        }

    async def get_score(self, site_id: str, property_id: str) -> dict | None:
        return await self._get_cached_insight(site_id, property_id, "quality_score")

    async def get_seo(self, site_id: str, property_id: str) -> dict | None:
        return await self._get_cached_insight(site_id, property_id, "seo_analysis")

    async def get_recommendations(self, site_id: str) -> list[dict]:
        result = await self._pb.list_records(
            COLLECTION_INSIGHTS,
            filter=f'site_id="{site_id}" && property_id!=""',
            per_page=500,
        )
        items = result.get("items", [])

        recommendations = []
        for item in items:
            content = item.get("content") or {}
            insight_type = item.get("insight_type", "")

            if insight_type == "quality_score":
                for rec in content.get("recommendations", []):
                    recommendations.append({
                        "property_id": item.get("property_id", ""),
                        "property_name": "",
                        "insight_type": insight_type,
                        "severity": "warning",
                        "message": rec,
                        "suggestion": "",
                    })
            elif insight_type == "seo_analysis":
                for issue in content.get("issues", []):
                    recommendations.append({
                        "property_id": item.get("property_id", ""),
                        "property_name": "",
                        "insight_type": insight_type,
                        "severity": issue.get("severity", "info"),
                        "field": issue.get("field"),
                        "message": issue.get("message", ""),
                        "suggestion": issue.get("suggestion", ""),
                    })

        return recommendations

    async def get_site_summary(self, site_id: str) -> dict | None:
        # Fetch all properties for the site
        props_result = await self._pb.list_records(
            COLLECTION_PROPERTIES,
            filter=f'site_id="{site_id}"',
            per_page=500,
        )
        properties = props_result.get("items", [])

        total = len(properties)
        published = sum(1 for p in properties if p.get("status") == "published")
        with_desc = sum(
            1 for p in properties
            if any(f.get("key") == "description" and f.get("value") for f in (p.get("fields") or []))
        )
        with_images = sum(
            1 for p in properties
            if any(f.get("key") in ("images", "image") and f.get("value") for f in (p.get("fields") or []))
        )

        # Count critical issues
        insights_result = await self._pb.list_records(
            COLLECTION_INSIGHTS,
            filter=f'site_id="{site_id}" && insight_type="seo_analysis"',
            per_page=500,
        )
        critical_issues = 0
        top_issues: list[str] = []
        for ins in insights_result.get("items", []):
            content = ins.get("content") or {}
            for issue in content.get("issues", []):
                if issue.get("severity") == "critical":
                    critical_issues += 1
                    top_issues.append(issue.get("message", ""))

        summary_input = SITE_SUMMARY_USER.format(
            site_id=site_id,
            total_products=total,
            published_products=published,
            products_with_description=with_desc,
            products_with_images=with_images,
            avg_quality_score=0,
            critical_issues=critical_issues,
            top_issues="; ".join(top_issues[:5]),
        )

        try:
            result = await self._llm.structured_output(SITE_SUMMARY_SYSTEM, summary_input)
        except Exception as e:
            logger.error("site summary LLM failed", extra={"error": str(e)})
            result = {
                "summary_text": f"Site has {total} products, {published} published.",
                "overall_health_score": 50,
                "key_metrics": {},
                "priority_actions": [],
            }

        result["site_id"] = site_id
        result["generated_at"] = datetime.now(UTC).isoformat()
        return result

    async def get_llm_health(self) -> dict:
        tracker = self._llm.tracker
        cache = self._llm.cache
        return {
            "status": "healthy" if self._llm._settings.enabled else "disabled",
            "provider": "openai",
            "model": self._llm._settings.model,
            "budget": {
                "monthly_limit_usd": self._llm._settings.monthly_budget_usd,
                "spent_usd": round(tracker.spent_usd, 4),
                "remaining_usd": round(tracker.remaining_usd, 4),
                "usage_pct": round(tracker.usage_pct, 1),
            },
            "cache": {
                "total_insights": cache.size,
            },
            "last_check": datetime.now(UTC).isoformat(),
        }

    async def _generate_insight(self, insight_type: str, fields: dict, prop: dict) -> dict:
        if insight_type == "quality_score":
            user_msg = QUALITY_SCORING_USER.format(**fields)
            return await self._llm.structured_output(QUALITY_SCORING_SYSTEM, user_msg)

        if insight_type == "seo_analysis":
            user_msg = SEO_ANALYSIS_USER.format(**fields)
            return await self._llm.structured_output(SEO_ANALYSIS_SYSTEM, user_msg)

        if insight_type == "content_optimization":
            user_msg = PRODUCT_OPTIMIZATION_USER.format(**fields)
            return await self._llm.structured_output(PRODUCT_OPTIMIZATION_SYSTEM, user_msg)

        return {}

    async def _get_cached_insight(self, site_id: str, property_id: str, insight_type: str) -> dict | None:
        try:
            result = await self._pb.list_records(
                COLLECTION_INSIGHTS,
                filter=f'site_id="{site_id}" && property_id="{property_id}" && insight_type="{insight_type}"',
                per_page=1,
            )
            items = result.get("items", [])
            if not items:
                return None
            item = items[0]
            return {
                "score": item.get("score"),
                "analyzed_at": item.get("generated_at", ""),
                "expires_at": item.get("expires_at"),
                **(item.get("content") or {}),
            }
        except Exception:
            return None

    async def _cache_insight(
        self,
        site_id: str,
        property_id: str,
        tenant_id: str,
        insight_type: str,
        content: dict,
        score: float | None = None,
    ) -> None:
        try:
            # Check if exists
            existing = await self._pb.list_records(
                COLLECTION_INSIGHTS,
                filter=f'site_id="{site_id}" && property_id="{property_id}" && insight_type="{insight_type}"',
                per_page=1,
            )
            items = existing.get("items", [])

            data = {
                "site_id": site_id,
                "property_id": property_id,
                "tenant_id": tenant_id,
                "insight_type": insight_type,
                "score": score,
                "content": content,
                "model_used": self._llm._settings.model,
                "tokens_used": 0,
                "generated_at": datetime.now(UTC).isoformat(),
                "expires_at": None,
            }

            if items:
                await self._pb.update_record(COLLECTION_INSIGHTS, items[0]["id"], data)
            else:
                data["insight_id"] = f"ins_{uuid.uuid4().hex[:12]}"
                await self._pb.create_record(COLLECTION_INSIGHTS, data)
        except Exception as e:
            logger.warning("insight cache failed", extra={"error": str(e)})
