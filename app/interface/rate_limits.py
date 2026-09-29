from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.infrastructure.rate_limits import allow_request
from app.interface.dependencies import TenantContext, get_tenant_context


async def _check(settings: Settings, quota: str, scope: str, identity: str) -> None:
    try:
        allowed = await allow_request(
            settings.rate_limit_storage_uri, quota, scope, identity
        )
    except Exception:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
    if not allowed:
        raise HTTPException(
            status_code=429, detail="Rate limit exceeded", headers={"Retry-After": "60"}
        )


def tenant_limit(scope: str, quota: str) -> Callable:
    async def check(
        ctx: TenantContext = Depends(get_tenant_context),
        settings: Settings = Depends(get_settings),
    ) -> None:
        await _check(settings, quota, scope, ctx.tenant_id)

    return check


async def public_submission_limit(
    request: Request, settings: Settings = Depends(get_settings)
) -> None:
    site_id = request.path_params.get("site_id", "")
    address = request.client.host if request.client else "unknown"
    await _check(settings, "5/minute", "public-submission-ip", address)
    await _check(settings, "100/minute", "public-submission-site", site_id)
