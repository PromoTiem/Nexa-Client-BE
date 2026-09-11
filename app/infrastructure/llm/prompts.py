"""LLM prompt templates for analytics and insights."""

PRODUCT_OPTIMIZATION_SYSTEM = """You are an e-commerce product optimization expert.
Analyze the product data and provide optimization suggestions.
Respond with valid JSON only."""

PRODUCT_OPTIMIZATION_USER = """Analyze this product listing and provide optimization suggestions:

Product Name: {name}
Type: {type}
Subtype: {subtype}
Status: {status}
Description: {description}
Price: {price}
Category: {category}
Tags: {tags}
SEO: {seo}
Excerpt: {excerpt}

Provide a JSON response with:
{{
  "title_suggestions": ["suggested title 1", "suggested title 2"],
  "description_improvements": ["improvement 1", "improvement 2"],
  "excerpt_suggestion": "suggested excerpt text",
  "completeness_score": 0-100,
  "missing_fields": ["field1", "field2"]
}}"""

SEO_ANALYSIS_SYSTEM = """You are an SEO specialist for e-commerce websites.
Analyze the product listing for SEO quality.
Respond with valid JSON only."""

SEO_ANALYSIS_USER = """Analyze this product listing for SEO quality:

Product Name: {name}
Slug: {slug}
Description: {description}
Excerpt: {excerpt}
SEO Title: {seo_title}
SEO Description: {seo_description}
Category: {category}
Tags: {tags}

Provide a JSON response with:
{{
  "title_score": 0-100,
  "meta_description_score": 0-100,
  "slug_score": 0-100,
  "keyword_suggestions": ["keyword1", "keyword2"],
  "issues": [
    {{
      "severity": "critical|warning|info",
      "field": "field_name",
      "message": "description of issue",
      "suggestion": "how to fix"
    }}
  ]
}}"""

QUALITY_SCORING_SYSTEM = """You are a product listing quality analyst.
Score the product listing quality from 0-100.
Respond with valid JSON only."""

QUALITY_SCORING_USER = """Score this product listing quality:

Product Name: {name}
Type: {type}
Description: {description}
Price: {price}
Category: {category}
Tags: {tags}
Images: {image_count} images
SEO: {seo}
Excerpt: {excerpt}

Provide a JSON response with:
{{
  "overall_score": 0-100,
  "breakdown": {{
    "completeness": 0-100,
    "seo": 0-100,
    "content_depth": 0-100,
    "image_quality": 0-100
  }},
  "recommendations": ["recommendation 1", "recommendation 2"]
}}"""

SITE_SUMMARY_SYSTEM = """You are an e-commerce site analyst.
Generate an executive summary of the site's product catalog health.
Respond with valid JSON only."""

SITE_SUMMARY_USER = """Generate an executive summary for this e-commerce site:

Site ID: {site_id}
Total Products: {total_products}
Published Products: {published_products}
Products with Description: {products_with_description}
Products with Images: {products_with_images}
Average Quality Score: {avg_quality_score}
Critical Issues: {critical_issues}
Top Issues: {top_issues}

Provide a JSON response with:
{{
  "summary_text": "2-3 sentence executive summary",
  "overall_health_score": 0-100,
  "key_metrics": {{
    "total_products": 0,
    "products_with_description": 0,
    "products_with_images": 0,
    "avg_quality_score": 0,
    "critical_issues": 0
  }},
  "priority_actions": ["action 1", "action 2"]
}}"""


def format_product_fields(properties: list[dict]) -> dict[str, str]:
    """Extract key fields from property records for prompt formatting."""
    result = {
        "name": "",
        "type": "",
        "subtype": "",
        "status": "",
        "description": "",
        "price": "",
        "category": "",
        "tags": "",
        "seo": "",
        "excerpt": "",
        "slug": "",
        "image_count": "0",
    }

    if not properties:
        return result

    prop = properties[0]
    result["name"] = prop.get("name", "")
    result["type"] = prop.get("type", "")
    result["subtype"] = prop.get("subtype", "")
    result["status"] = prop.get("status", "")
    result["excerpt"] = prop.get("excerpt") or ""
    result["slug"] = prop.get("slug") or ""

    seo = prop.get("seo") or {}
    result["seo_title"] = seo.get("title", "")
    result["seo_description"] = seo.get("description", "")

    fields = prop.get("fields", [])
    for field in fields:
        key = field.get("key", "")
        value = field.get("value")
        if key == "description":
            result["description"] = str(value or "")
        elif key == "price":
            result["price"] = str(value or "")
        elif key == "category":
            result["category"] = str(value or "")
        elif key == "tags":
            result["tags"] = str(value or "")
        elif key == "images":
            if isinstance(value, list):
                result["image_count"] = str(len(value))

    return result
