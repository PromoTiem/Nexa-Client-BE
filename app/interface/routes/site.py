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
    AuthContext,
    get_auth_context,
    get_cloudflare_client,
    get_pocketbase_client,
    get_storage_client,
)
from app.interface.route_helpers import (
    auth_tenant,
    ensure_tenant_owns,
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
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> SiteListResponse:
    # Tenant-scoped tokens are always filtered to their own tenant; any
    # incompatible query value is overridden.
    effective_tenant = auth_tenant(auth) or tenant_id
    filter_expr = None
    if effective_tenant:
        tenant_record_id = await public_id_to_record_id(
            pb, "tenants", "tenant_id", effective_tenant, auth.token
        )
        filter_expr = f'tenant_id="{tenant_record_id}"'
    result = await pb.list_records(
        collection=COLLECTION,
        token=auth.token,
        filter=filter_expr,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    items = [
        _record_to_response(await map_site_record(r, auth.token, pb, fields=("tenant_id", "template_id", "domain_id")))
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
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    storage: StorageClient = Depends(get_storage_client),
) -> SiteResponse:
    validate_id(body.site_id, "site_id")
    tenant = auth_tenant(auth)
    if tenant and body.tenant_id != tenant:
        raise HTTPException(
            status_code=403, detail="Cannot create site for another tenant"
        )
    tenant_record_id = await public_id_to_record_id(
        pb, "tenants", "tenant_id", body.tenant_id, auth.token
    )
    template_record_id = await public_id_to_record_id(
        pb, "templates", "template_id", body.template_id, auth.token
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
            token=auth.token,
            user_id=auth.record["id"],
        )
    except Exception:
        await delete_bucket_for_site(bucket_name, storage)
        raise

    return _record_to_response(await map_site_record(record, auth.token, pb, fields=("tenant_id", "template_id", "domain_id")))


@router.get("/{site_id}", response_model=SiteResponse)
async def get_site(
    site_id: str,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> SiteResponse:
    validate_id(site_id, "site_id")
    record = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=auth.token,
    )
    record = await map_site_record(record, auth.token, pb, fields=("tenant_id", "template_id", "domain_id"))
    ensure_tenant_owns(record, auth)
    return _record_to_response(record)


@router.patch("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: str,
    body: SiteUpdateRequest,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
) -> SiteResponse:
    validate_id(site_id, "site_id")
    existing = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=auth.token,
    )
    mapped_existing = await map_site_record(existing, auth.token, pb, fields=("tenant_id", "template_id", "domain_id"))
    ensure_tenant_owns(mapped_existing, auth)

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
            pb, "templates", "template_id", body.template_id, auth.token
        )
    if body.domain is not None:
        update_data["domain"] = body.domain
    if body.domain_id is not None:
        if body.domain_id == "":
            update_data["domain_id"] = ""  # unlink
        else:
            dom_record_id = await public_id_to_record_id(
                pb, "domains", "domain_id", body.domain_id, auth.token
            )
            tenant = auth_tenant(auth)
            if tenant:
                dom = await pb.find_one_by_filter(
                    collection="domains",
                    filter_expr=f'id="{dom_record_id}"',
                    token=auth.token,
                )
                dom_tenant_public = await record_id_to_public_id(
                    pb, "tenants", "tenant_id", dom.get("tenant_id"), auth.token
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
        token=auth.token,
        user_id=auth.record["id"],
    )
    return _record_to_response(await map_site_record(record, auth.token, pb, fields=("tenant_id", "template_id", "domain_id")))


@router.delete("/{site_id}", status_code=204)
async def delete_site(
    site_id: str,
    auth: AuthContext = Depends(get_auth_context),
    pb: PocketBaseClient = Depends(get_pocketbase_client),
    cf: CloudflareClient = Depends(get_cloudflare_client),
    storage: StorageClient = Depends(get_storage_client),
) -> Response:
    validate_id(site_id, "site_id")
    existing = await pb.find_one_by_filter(
        collection=COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=auth.token,
    )
    mapped_existing = await map_site_record(existing, auth.token, pb, fields=("tenant_id", "template_id", "domain_id"))
    ensure_tenant_owns(mapped_existing, auth)

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

    await cleanup_all_domains(project_name, existing.get("domain_id"), cf, pb, auth.token)

    try:
        await delete_bucket_for_site(sanitize_bucket_name(site_id), storage)
    except Exception as e:
        logger.warning("failed to delete bucket during delete", extra={"site_id": site_id, "error": str(e)})

    await pb.delete_record(
        collection=COLLECTION,
        record_id=existing["id"],
        token=auth.token,
    )
    return Response(status_code=204)
