from typing import Any

from pydantic import BaseModel, Field

# --- Quality Score ---


class QualityBreakdown(BaseModel):
    completeness: int = 0
    seo: int = 0
    content_depth: int = 0
    image_quality: int = 0


class QualityScoreResponse(BaseModel):
    property_id: str
    score: int
    breakdown: QualityBreakdown
    recommendations: list[str] = Field(default_factory=list)
    analyzed_at: str
    expires_at: str | None = None


# --- SEO Analysis ---


class SEOIssue(BaseModel):
    severity: str  # critical, warning, info
    field: str
    message: str
    suggestion: str


class SEOAnalysisResponse(BaseModel):
    property_id: str
    title_score: int = 0
    meta_description_score: int = 0
    slug_score: int = 0
    keyword_suggestions: list[str] = Field(default_factory=list)
    issues: list[SEOIssue] = Field(default_factory=list)
    analyzed_at: str


# --- Content Optimization ---


class ContentOptimizationResponse(BaseModel):
    property_id: str
    title_suggestions: list[str] = Field(default_factory=list)
    description_improvements: list[str] = Field(default_factory=list)
    excerpt_suggestion: str = ""
    analyzed_at: str


# --- Site Summary ---


class SiteSummaryResponse(BaseModel):
    site_id: str
    overall_health_score: int = 0
    summary_text: str = ""
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    priority_actions: list[str] = Field(default_factory=list)
    generated_at: str


# --- Batch Analysis ---


class BatchAnalysisRequest(BaseModel):
    type: str = "all"  # all, quality_score, seo_analysis, content_optimization
    force: bool = False
    property_type: str | None = None


class BatchAnalysisStatusResponse(BaseModel):
    site_id: str
    job_id: str
    total_products: int
    queued: int
    status: str
    estimated_tokens: int = 0
    estimated_cost_usd: float = 0.0


# --- Analyze Request ---


class AnalyzeRequest(BaseModel):
    force: bool = False
    type: str = "all"  # all, quality_score, seo_analysis, content_optimization


# --- Recommendations ---


class RecommendationItem(BaseModel):
    property_id: str
    property_name: str
    insight_type: str
    severity: str
    field: str | None = None
    message: str
    suggestion: str


class RecommendationsResponse(BaseModel):
    site_id: str
    total_recommendations: int
    by_priority: dict[str, int] = Field(default_factory=dict)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    generated_at: str


# --- LLM Health ---


class LLMHealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    budget: dict[str, Any] = Field(default_factory=dict)
    cache: dict[str, Any] = Field(default_factory=dict)
    last_check: str
