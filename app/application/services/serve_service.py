from typing import Optional

import re

from app.application.services.site_deployer import (
    deploy_site,
    remove_dns_for_domain,
    remove_domain_from_pages,
    sanitize_project_name,
)
from app.config import get_settings
from app.infrastructure.logging import get_logger
from app.interface.dto.serve import (
    PipelineBuild,
    PipelineDomain,
    PipelineResponse,
    PipelineServe,
    ServeStateResponse,
    SiteServeResponse,
    SiteStopResponse,
)

logger = get_logger("serve_service")

SITES_COLLECTION = "sites"


class ServeTransitionError(Exception):
    """Invalid transition, wrong serve_status, or double-submit -> 409."""


class DomainNotVerifiedError(Exception):
    """Custom domain sent but no verified domains record -> 400."""


class NoCompletedBuildError(Exception):
    """No completed build available for deployment -> 400."""


class ServeDeployError(Exception):
    """Deploy failed; carries a sanitized message -> 500."""


SERVE_TRANSITIONS = {
    None: {"requested"},
    "requested": {"verifying", "failed"},
    "verifying": {"verified", "failed"},
    "verified": {"serving"},
    "serving": {"live", "failed"},
    "live": {"stopped"},
    "failed": {"requested"},
    "stopped": {"requested"},
}


def normalize_serve_status(raw: Optional[str]) -> Optional[str]:
    if raw is None or raw == "":
        return None
    return raw


def update_stage_log(log: Optional[dict], target: Optional[str] = None) -> dict:
    from app.application.services.utils import utc_now_iso
    result = dict(log) if isinstance(log, dict) else {}
    if target is not None:
        result[f"{target}_at"] = utc_now_iso()
    return result


def assert_transition(current: Optional[str], target: str) -> None:
    allowed = SERVE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ServeTransitionError(
            f"invalid serve transition {current!r} -> {target!r}"
        )


async def patch_status(*, pb, site_record, target, token, user_id) -> ServeStateResponse:
    site_id = site_record["site_id"]
    current = normalize_serve_status(site_record.get("serve_status"))
    assert_transition(current, target)
    log = update_stage_log(site_record.get("serve_stage_log"), target)
    await pb.update_record(
        collection=SITES_COLLECTION,
        record_id=site_record["id"],
        data={"serve_status": target, "serve_stage_log": log},
        token=token,
        user_id=user_id,
    )
    return ServeStateResponse(site_id=site_id, serve_status=target, serve_stage_log=log)


async def serve(*, pb, cf, storage, site_record, token, user_id) -> SiteServeResponse:
    site_id = site_record["site_id"]

    if normalize_serve_status(site_record.get("serve_status")) != "verified":
        raise ServeTransitionError(
            f"serve_status must be 'verified', got "
            f"{normalize_serve_status(site_record.get('serve_status'))!r}"
        )

    settings = get_settings()
    project_name = sanitize_project_name(site_id)

    domain_rec_id = site_record.get("domain_id")
    if domain_rec_id:
        linked = await pb.find_one_by_filter(
            collection="domains",
            filter_expr=f'id="{domain_rec_id}"',
            token=token,
        )
        if linked.get("status") != "verified":
            raise DomainNotVerifiedError("linked domain not verified")
        deploy_domain = linked["domain"]
    else:
        deploy_domain = f"{project_name}.{settings.site_base_domain}"

    builds = await pb.list_records(
        collection="builds",
        token=token,
        filter=f'site_id="{site_id}"&&status="completed"',
        sort="-created_at",
        page=1,
        per_page=1,
    )
    if not builds.get("items"):
        raise NoCompletedBuildError("no completed build available for deployment")
    latest_build = builds["items"][0]

    fresh = await pb.find_one_by_filter(
        collection=SITES_COLLECTION,
        filter_expr=f'site_id="{site_id}"',
        token=token,
    )
    if normalize_serve_status(fresh.get("serve_status")) != "verified":
        raise ServeTransitionError("deploy already in progress")
    assert_transition("verified", "serving")
    serving_log = update_stage_log(fresh.get("serve_stage_log"), "serving")
    await pb.update_record(
        collection=SITES_COLLECTION,
        record_id=fresh["id"],
        data={"serve_status": "serving", "serve_stage_log": serving_log},
        token=token,
        user_id=user_id,
    )

    try:
        files = await _extract_static_files_from_storage(storage, latest_build["image"])
        if not files:
            raise RuntimeError("no static files found in build image")
        result = await deploy_site(
            files=files,
            project_name=project_name,
            cf=cf,
            base_domain=deploy_domain,
        )
    except Exception as deploy_err:
        try:
            fail_log = update_stage_log(serving_log, "failed")
            await pb.update_record(
                collection=SITES_COLLECTION,
                record_id=fresh["id"],
                data={"serve_status": "failed", "serve_stage_log": fail_log},
                token=token,
                user_id=user_id,
            )
        except Exception as bookkeeping_err:
            logger.error(
                "failed to write serve_status=failed after deploy failure",
                extra={"site_id": site_id, "error": str(bookkeeping_err)},
            )
        logger.warning(
            "serve deploy failed",
            extra={"site_id": site_id, "error": str(deploy_err)},
        )
        raise ServeDeployError("deployment failed") from deploy_err

    if result.get("dns_setup_failed") or result.get("domain_setup_failed"):
        try:
            fail_log = update_stage_log(serving_log, "failed")
            await pb.update_record(
                collection=SITES_COLLECTION,
                record_id=fresh["id"],
                data={"serve_status": "failed", "serve_stage_log": fail_log},
                token=token,
                user_id=user_id,
            )
        except Exception as bookkeeping_err:
            logger.error(
                "failed to write serve_status=failed after dns/binding failure",
                extra={"site_id": site_id, "error": str(bookkeeping_err)},
            )
        logger.warning(
            "serve dns/binding failed",
            extra={
                "site_id": site_id,
                "domain": deploy_domain,
                "dns_setup_failed": result.get("dns_setup_failed"),
                "domain_setup_failed": result.get("domain_setup_failed"),
            },
        )
        raise ServeDeployError("dns or domain binding failed")

    live_log = update_stage_log(serving_log, "live")
    await pb.update_record(
        collection=SITES_COLLECTION,
        record_id=fresh["id"],
        data={"serve_status": "live", "serve_stage_log": live_log, "status": "live"},
        token=token,
        user_id=user_id,
    )
    return SiteServeResponse(
        site_id=site_id,
        build_id=latest_build["build_id"],
        pages_url=result["pages_url"],
        custom_domain=result.get("custom_domain") or deploy_domain,
        deployment_url=result["deployment_url"],
        serve_status="live",
    )


async def stop(*, pb, cf, site_record, token, user_id) -> SiteStopResponse:
    site_id = site_record["site_id"]
    if normalize_serve_status(site_record.get("serve_status")) != "live":
        raise ServeTransitionError(
            f"serve_status must be 'live', got "
            f"{normalize_serve_status(site_record.get('serve_status'))!r}"
        )

    settings = get_settings()
    project_name = sanitize_project_name(site_id)
    derived_domain = f"{project_name}.{settings.site_base_domain}"

    custom_domains = []
    domain_rec_id = site_record.get("domain_id")
    if domain_rec_id:
        try:
            linked = await pb.find_one_by_filter(
                collection="domains",
                filter_expr=f'id="{domain_rec_id}"',
                token=token,
            )
            if (
                linked.get("domain")
                and linked.get("status") == "verified"
                and linked["domain"] != derived_domain
            ):
                custom_domains = [linked["domain"]]
        except Exception as e:
            logger.warning(
                "linked domain lookup failed during stop",
                extra={"error": str(e)},
            )

    unbind_error: Optional[Exception] = None
    for cd in custom_domains + [derived_domain]:
        try:
            await remove_domain_from_pages(project_name, cd, cf)
        except Exception as e:
            unbind_error = unbind_error or e
            logger.warning(
                "pages unbind failed",
                extra={"domain": cd, "error": str(e)},
            )
        try:
            zone_id = None if cd == derived_domain else await cf.resolve_zone_id(cd)
            await remove_dns_for_domain(cd, cf, zone_id)
        except Exception as e:
            logger.info(
                "domain CNAME cleanup skipped",
                extra={"domain": cd, "error": str(e)},
            )
    if unbind_error is not None:
        raise unbind_error

    stopped_log = update_stage_log(site_record.get("serve_stage_log"), "stopped")
    await pb.update_record(
        collection=SITES_COLLECTION,
        record_id=site_record["id"],
        data={
            "serve_status": "stopped",
            "serve_stage_log": stopped_log,
            "status": "draft",
        },
        token=token,
        user_id=user_id,
    )
    return SiteStopResponse(
        site_id=site_id,
        status="draft",
        custom_domain=derived_domain,
        pages_url=f"https://{project_name}.pages.dev",
        serve_status="stopped",
    )


async def get_pipeline(*, pb, site_record, token) -> PipelineResponse:
    site_id = site_record["site_id"]

    builds = await pb.list_records(
        collection="builds",
        token=token,
        filter=f'site_id="{site_id}"',
        sort="-created_at",
        page=1,
        per_page=1,
    )
    build = None
    if builds.get("items"):
        b = builds["items"][0]
        build = PipelineBuild(
            latest_build_id=b.get("build_id"),
            build_status=b.get("status"),
        )

    raw_log = site_record.get("serve_stage_log")
    serve = PipelineServe(
        status=normalize_serve_status(site_record.get("serve_status")),
        stage_log=raw_log if isinstance(raw_log, dict) else {},
    )

    domain = None
    domain_rec_id = site_record.get("domain_id")
    if domain_rec_id:
        d = await pb.find_one_by_filter(
            collection="domains",
            filter_expr=f'id="{domain_rec_id}"',
            token=token,
        )
        domain = PipelineDomain(
            domain_id=d.get("domain_id"),
            domain=d.get("domain"),
            status=d.get("status"),
        )

    return PipelineResponse(site_id=site_id, build=build, serve=serve, domain=domain)


async def _extract_static_files_from_storage(
    storage, image_key: str
) -> dict:
    parsed = re.match(r"s3://([^/]+)/(.+)", image_key)
    if not parsed:
        raise ValueError(f"invalid image key format: {image_key}")
    bucket = parsed.group(1)
    prefix = parsed.group(2)

    objects = await storage.list_objects(bucket=bucket, prefix=prefix)
    files = {}
    for obj in objects.get("Contents", []):
        key = obj["Key"]
        if key.endswith("/"):
            continue
        relative = key[len(prefix):].lstrip("/")
        if not relative:
            continue
        obj_data = await storage.get_object(bucket=bucket, key=key)
        files[relative] = obj_data["Body"].read()
    return files
