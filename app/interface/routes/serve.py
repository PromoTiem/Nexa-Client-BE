from fastapi import APIRouter, Depends, HTTPException

from app.application.services import serve_service
from app.application.services.serve_service import (
    DomainNotVerifiedError,
    NoCompletedBuildError,
    ServeDeployError,
    ServeTransitionError,
)
from app.infrastructure.cloudflare.client import CloudflareClient
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.storage.client import StorageClient
from app.interface.dependencies import (
    TenantContext,
    get_cloudflare_client,
    get_pocketbase_client,
    get_storage_client,
    get_tenant_context,
)
from app.interface.dto.serve import (
    PipelineResponse,
    ServeStateResponse,
    ServeStatusPatchRequest,
    SiteServeResponse,
    SiteStopResponse,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import (
    map_site_record,
    public_id_to_record_id,
    validate_id,
)

COLLECTION = "sites"

router = APIRouter()


async def _load_site(
    site_id: str, ctx: TenantContext, pb: PocketBaseClient
) -> dict:
    validate_id(site_id, "site_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=ctx.token,
    )
    mapped = await map_site_record(
        record, ctx.token, pb, fields=("tenant_id",)
    )
    ctx.enforce_owns(mapped)
    return record


@router.patch("/{site_id}/serve/status", response_model=ServeStateResponse)
async def patch_serve_status(
    site_id: str,
    body: ServeStatusPatchRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> ServeStateResponse:
    enforce_permission(ctx.auth, Permission.SERVE_ACCESS)
    record = await _load_site(site_id, ctx, pb)
    try:
        return await serve_service.patch_status(
            pb=pb,
            site_record=record,
            target=body.status,
            token=ctx.token,
            user_id=ctx.user_id,
        )
    except ServeTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{site_id}/serve", response_model=SiteServeResponse)
async def serve_site(
    site_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    cf: CloudflareClient = Depends(get_cloudflare_client),
    storage: StorageClient = Depends(get_storage_client),
) -> SiteServeResponse:
    enforce_permission(ctx.auth, Permission.SERVE_ACCESS)
    record = await _load_site(site_id, ctx, pb)
    try:
        return await serve_service.serve(
            pb=pb,
            cf=cf,
            storage=storage,
            site_record=record,
            token=ctx.token,
            user_id=ctx.user_id,
        )
    except ServeTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DomainNotVerifiedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NoCompletedBuildError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ServeDeployError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{site_id}/stop", response_model=SiteStopResponse)
async def stop_site(
    site_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    cf: CloudflareClient = Depends(get_cloudflare_client),
) -> SiteStopResponse:
    enforce_permission(ctx.auth, Permission.SERVE_ACCESS)
    record = await _load_site(site_id, ctx, pb)
    try:
        return await serve_service.stop(
            pb=pb,
            cf=cf,
            site_record=record,
            token=ctx.token,
            user_id=ctx.user_id,
        )
    except ServeTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{site_id}/pipeline", response_model=PipelineResponse)
async def get_pipeline(
    site_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> PipelineResponse:
    enforce_permission(ctx.auth, Permission.SERVE_ACCESS)
    record = await _load_site(site_id, ctx, pb)
    return await serve_service.get_pipeline(
        pb=pb, site_record=record, token=ctx.token
    )
