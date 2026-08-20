from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.application.services.bucket_resolver import (
    create_bucket_for_site,
    delete_bucket_for_site,
    sanitize_bucket_name,
)
from app.application.services.site_deployer import (
    cleanup_all_domains,
    remove_domain_from_pages,
    remove_dns_for_domain,
    sanitize_project_name,
)
from app.config import get_settings
from app.infrastructure.cloudflare.client import CloudflareClient
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.storage.client import StorageClient
from app.interface.dependencies import (
    TenantContext,
    get_cloudflare_client,
    get_pocketbase_client,
    get_storage_client,
    get_tenant_context,
)
from app.interface.rbac import Permission, enforce_permission
from app.interface.route_helpers import (
    map_site_record,
    public_id_to_record_id,
    record_id_to_public_id,
    validate_id,
)
from app.interface.dto.site import (
    SiteCreateRequest,
    SiteListResponse,
    SiteResponse,
    SiteUpdateRequest,
)

COLLECTION = "sites"

router = APIRouter()
logger = get_logger("site_routes")


def _record_to_response(record: Dict[str, Any]) -> SiteResponse:
    return SiteResponse(
        id=record["id"],
        site_id=record["site_id"],
        tenant_id=record.get("tenant_id"),
        template_id=record.get("template_id"),
        domain=record.get("domain"),
        domain_id=record.get("domain_id"),
        config=record.get("config"),
        status=record.get("status") or None,
        bucket_name=record.get("bucket_name") or None,
        bucket_description=record.get("bucket_description") or None,
        bucket_public=bool(record.get("bucket_public", False)),
        serve_status=(record.get("serve_status") or None),
        serve_stage_log=(record.get("serve_stage_log") or None),
        default=record.get("default") or False,
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
        created_by=record.get("created_by"),
        updated_by=record.get("updated_by"),
    )


@router.get("", response_model=SiteListResponse)
async def list_sites(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query("-created_at"),
    tenant_id: Optional[str] = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> SiteListResponse:
    enforce_permission(ctx.auth, Permission.SITES_LIST)
    effective_tenant = ctx.tenant_id or tenant_id
    filter_expr = None
    if effective_tenant:
        tenant_record_id = await public_id_to_record_id(
            pb, "tenants", "tenant_id", effective_tenant, ctx.token
        )
        filter_expr = f'tenant_id="{tenant_record_id}"'
    result = await pb.list_records(
        collection=COLLECTION,
        token=ctx.token,
        filter=filter_expr,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = [
        _record_to_response(await map_site_record(r, ctx.token, pb, fields=("tenant_id", "template_id", "domain_id")))
        for r in result.get("items", [])
    ]
    return SiteListResponse(
        items=items,
        total=result.get("totalItems", 0),
        page=result.get("page", page),
        per_page=result.get("perPage", per_page),
        total_pages=result.get("totalPages", 0),
    )


@router.post("", response_model=SiteResponse, status_code=201)
async def create_site(
    body: SiteCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    storage: StorageClient = Depends(get_storage_client),
) -> SiteResponse:
    enforce_permission(ctx.auth, Permission.SITES_CREATE)
    validate_id(body.site_id, "site_id")
    tenant = ctx.tenant_id
    if not tenant:
        raise HTTPException(
            status_code=403, detail="Client access requires tenant_id"
        )
    tenant_record_id = await public_id_to_record_id(
        pb, "tenants", "tenant_id", tenant, ctx.token
    )
    template_record_id = await public_id_to_record_id(
        pb, "templates", "template_id", body.template_id, ctx.token
    )

    await create_bucket_for_site(body.site_id, storage)

    bucket_name = sanitize_bucket_name(body.site_id)
    data: Dict[str, Any] = {
        "site_id": body.site_id,
        "tenant_id": tenant_record_id,
        "template_id": template_record_id,
        "domain": body.domain,
        "status": body.status or "draft",
        "bucket_name": bucket_name,
        "default": body.default or False,
    }
    if body.config is not None:
        data["config"] = body.config

    try:
        record = await pb.create_record(
            collection=COLLECTION,
            data=data,
            token=ctx.token,
            user_id=ctx.user_id,
        )
    except Exception:
        await delete_bucket_for_site(bucket_name, storage)
        raise

    return _record_to_response(await map_site_record(record, ctx.token, pb, fields=("tenant_id", "template_id", "domain_id")))


@router.get("/{site_id}", response_model=SiteResponse)
async def get_site(
    site_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> SiteResponse:
    enforce_permission(ctx.auth, Permission.SITES_LIST)
    validate_id(site_id, "site_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=ctx.token,
    )
    record = await map_site_record(record, ctx.token, pb, fields=("tenant_id", "template_id", "domain_id"))
    ctx.enforce_owns(record)
    return _record_to_response(record)


@router.patch("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: str,
    body: SiteUpdateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> SiteResponse:
    enforce_permission(ctx.auth, Permission.SITES_UPDATE)
    validate_id(site_id, "site_id")
    existing = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=ctx.token,
    )
    mapped_existing = await map_site_record(existing, ctx.token, pb, fields=("tenant_id", "template_id", "domain_id"))
    ctx.enforce_owns(mapped_existing)

    if (
        body.template_id is None
        and body.domain is None
        and body.domain_id is None
        and body.config is None
        and body.status is None
        and body.default is None
    ):
        return _record_to_response(mapped_existing)

    update_data: Dict[str, Any] = {}
    if body.template_id is not None:
        update_data["template_id"] = await public_id_to_record_id(
            pb, "templates", "template_id", body.template_id, ctx.token
        )
    if body.domain is not None:
        update_data["domain"] = body.domain
    if body.domain_id is not None:
        if body.domain_id == "":
            update_data["domain_id"] = ""  # unlink
        else:
            dom_record_id = await public_id_to_record_id(
                pb, "domains", "domain_id", body.domain_id, ctx.token
            )
            tenant = ctx.tenant_id
            if tenant:
                dom = await pb.find_one_by_filter(
                    collection="domains",
                    filter_expr=f'id="{dom_record_id}"',
                    token=ctx.token,
                )
                dom_tenant_public = await record_id_to_public_id(
                    pb, "tenants", "tenant_id", dom.get("tenant_id"), ctx.token
                )
                if dom_tenant_public != tenant:
                    raise HTTPException(status_code=404, detail="Domain not found")
            update_data["domain_id"] = dom_record_id
    if body.config is not None:
        update_data["config"] = body.config
    if body.status is not None:
        update_data["status"] = body.status
    if body.default is not None:
        update_data["default"] = body.default
    record = await pb.update_record(
        collection=COLLECTION,
        record_id=existing["id"],
        data=update_data,
        token=ctx.token,
        user_id=ctx.user_id,
    )
    return _record_to_response(await map_site_record(record, ctx.token, pb, fields=("tenant_id", "template_id", "domain_id")))


@router.delete("/{site_id}", status_code=204)
async def delete_site(
    site_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    cf: CloudflareClient = Depends(get_cloudflare_client),
    storage: StorageClient = Depends(get_storage_client),
) -> Response:
    enforce_permission(ctx.auth, Permission.SITES_DELETE)
    validate_id(site_id, "site_id")
    existing = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=ctx.token,
    )
    mapped_existing = await map_site_record(existing, ctx.token, pb, fields=("tenant_id", "template_id", "domain_id"))
    ctx.enforce_owns(mapped_existing)

    project_name = sanitize_project_name(site_id)
    base_domain = get_settings().site_base_domain
    custom_domain = f"{project_name}.{base_domain}"

    try:
        await remove_domain_from_pages(project_name, custom_domain, cf)
    except Exception as e:
        logger.warning("failed to remove domain from pages during delete", extra={"site_id": site_id, "error": str(e)})

    try:
        await remove_dns_for_domain(custom_domain, cf)
    except Exception as e:
        logger.warning("failed to remove DNS during delete", extra={"site_id": site_id, "error": str(e)})

    await cleanup_all_domains(project_name, existing.get("domain_id"), cf, pb, ctx.token)

    try:
        await delete_bucket_for_site(sanitize_bucket_name(site_id), storage)
    except Exception as e:
        logger.warning("failed to delete bucket during delete", extra={"site_id": site_id, "error": str(e)})

    await pb.delete_record(
        collection=COLLECTION,
        record_id=existing["id"],
        token=ctx.token,
    )
    return Response(status_code=204)
