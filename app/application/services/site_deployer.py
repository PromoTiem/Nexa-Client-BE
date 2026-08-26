import os
import re
import shutil
import tempfile
from typing import Any

from fastapi import HTTPException

from app.application.services.utils import run_subprocess, sanitize_name
from app.config import get_settings
from app.infrastructure.cloudflare.client import (
    CloudflareClient,
    CloudflareZoneNotFoundError,
)
from app.infrastructure.logging import get_logger

logger = get_logger("site_deployer")


def sanitize_project_name(template_id: str) -> str:
    return sanitize_name(template_id, max_length=58)


async def ensure_project(
    project_name: str, cf: CloudflareClient, production_branch: str = "main"
) -> dict[str, Any]:
    try:
        result = await cf.get_project(project_name)
        return result.get("result", {})
    except HTTPException as e:
        if e.status_code == 404:
            try:
                result = await cf.create_project(
                    name=project_name,
                    production_branch=production_branch,
                )
                return result.get("result", {})
            except HTTPException as create_err:
                if create_err.status_code in (409, 400):
                    result = await cf.get_project(project_name)
                    return result.get("result", {})
                raise
        raise


async def deploy_to_pages(
    project_name: str,
    files: dict[str, bytes],
    cf: CloudflareClient,
    branch: str = "main",
) -> str:
    temp_dir = tempfile.mkdtemp(prefix="nexa-deploy-")
    try:
        for path, content in files.items():
            file_path = os.path.join(temp_dir, path)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(content)

        cmd = [
            "npx",
            "--yes",
            "wrangler@3",
            "pages",
            "deploy",
            temp_dir,
            "--project-name",
            project_name,
            "--branch",
            branch,
            "--commit-dirty=true",
        ]

        env = {
            "CLOUDFLARE_API_TOKEN": cf.api_token,
            "CLOUDFLARE_ACCOUNT_ID": cf.account_id,
        }

        rc, stdout, stderr = await run_subprocess(cmd, env=env, timeout=300)

        if rc != 0:
            error_msg = stderr or stdout or "Unknown error"
            raise RuntimeError(f"Wrangler deploy failed (exit {rc}): {error_msg}")

        logger.info(
            "wrangler deploy output",
            extra={"stdout": stdout[:500], "stderr": stderr[:500]},
        )
        for line in stdout.split("\n"):
            if "https://" in line and ".pages.dev" in line:
                match = re.search(r"https://[a-z0-9.-]+\.pages\.dev", line)
                if match:
                    return match.group(0)

        return f"https://{project_name}.pages.dev"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def add_custom_domain(
    project_name: str,
    domain: str,
    cf: CloudflareClient,
) -> dict[str, Any]:
    try:
        result = await cf.add_domain(project_name, domain)
        return result.get("result", {})
    except HTTPException as e:
        if e.status_code in (400, 409):
            existing = await cf.get_domain(project_name, domain)
            return existing.get("result", {})
        raise


async def setup_dns(
    subdomain: str,
    pages_dev_url: str,
    cf: CloudflareClient,
    zone_id: str | None = None,
) -> dict[str, Any] | None:
    zone_id = zone_id or cf.zone_id
    if not zone_id:
        return None

    target = pages_dev_url.replace("https://", "").replace("http://", "")
    target = target.rstrip("/")

    records = await cf.list_dns_records(zone_id, record_type="CNAME", name=subdomain)
    existing = records.get("result", [])
    if existing:
        existing_target = existing[0].get("content", "")
        if existing_target.rstrip(".") != target.rstrip("."):
            logger.info(
                "updating existing DNS record with new target",
                extra={
                    "subdomain": subdomain,
                    "old_target": existing_target,
                    "new_target": target,
                },
            )
            await cf.delete_dns_record(zone_id, existing[0]["id"])
            result = await cf.create_dns_record(
                zone_id,
                record_type="CNAME",
                name=subdomain,
                content=target,
                proxied=True,
                ttl=1,
            )
            return result.get("result", {})
        return existing[0]

    result = await cf.create_dns_record(
        zone_id,
        record_type="CNAME",
        name=subdomain,
        content=target,
        proxied=True,
        ttl=1,
    )
    return result.get("result", {})


async def remove_domain_from_pages(
    project_name: str,
    domain: str,
    cf: CloudflareClient,
) -> bool:
    try:
        await cf.delete_domain(project_name, domain)
        logger.info(
            "removed domain from pages",
            extra={"project": project_name, "domain": domain},
        )
        return True
    except HTTPException as e:
        if e.status_code == 404:
            logger.info(
                "domain not found on pages (already removed)",
                extra={"project": project_name, "domain": domain},
            )
            return False
        raise


async def remove_dns_for_domain(
    subdomain: str,
    cf: CloudflareClient,
    zone_id: str | None = None,
) -> bool:
    zone_id = zone_id or cf.zone_id
    if not zone_id:
        return False

    records = await cf.list_dns_records(zone_id, record_type="CNAME", name=subdomain)
    existing = records.get("result", [])
    if not existing:
        logger.info(
            "dns record not found (already removed)", extra={"subdomain": subdomain}
        )
        return False

    for record in existing:
        await cf.delete_dns_record(zone_id, record["id"])
        logger.info(
            "removed dns record",
            extra={"subdomain": subdomain, "record_id": record["id"]},
        )
    return True


async def delete_cname_record(cf, domain: str, zone_id: str | None = None) -> None:
    """Best-effort delete of a custom domain's CNAME in its resolved zone.

    Pass ``zone_id`` to reuse an already-resolved zone (avoids a redundant
    ``GET /zones`` when the caller cleans up several record types at once).
    """
    zone_id = zone_id or await cf.resolve_zone_id(domain)
    await remove_dns_for_domain(domain, cf, zone_id)


async def delete_txt_verification_record(
    cf, domain: str, token: str, zone_id: str | None = None
) -> None:
    """Best-effort delete of a domain's DNS TXT verification record."""
    zone_id = zone_id or await cf.resolve_zone_id(domain)
    # per_page default (20) is plenty: TXT records are filtered to name=domain,
    # so at most a handful ever match. ponytail: paginate if that ever grows.
    resp = await cf.list_dns_records(zone_id, record_type="TXT", name=domain)
    for record in resp.get("result", []):
        if token and token in record.get("content", ""):
            await cf.delete_dns_record(zone_id, record["id"])


async def cleanup_all_domains(
    project_name: str,
    domain_record_id: str | None,
    cf: CloudflareClient,
    pb,
    token: str,
) -> None:
    """Best-effort removal of the site's single linked custom domain."""
    if not domain_record_id:
        return
    try:
        rec = await pb.find_one_by_filter(
            collection="domains",
            filter_expr=f'id="{domain_record_id}"',
            token=token,
        )
    except Exception as e:
        logger.warning(
            "failed to load linked domain for cleanup",
            extra={"domain_record_id": domain_record_id, "error": str(e)},
        )
        return
    domain = rec.get("domain")
    if not domain:
        return
    try:
        await remove_domain_from_pages(project_name, domain, cf)
    except Exception as e:
        logger.warning(
            "CF Pages cleanup failed",
            extra={"domain": domain, "error": str(e)},
        )


async def deploy_site(
    files: dict[str, bytes],
    project_name: str,
    cf: CloudflareClient,
    base_domain: str | None = None,
) -> dict[str, Any]:
    await ensure_project(project_name, cf)

    pages_url = await deploy_to_pages(project_name, files, cf)

    custom_domain = None
    dns_record = None
    dns_setup_failed = False
    domain_setup_failed = False
    if base_domain:
        project_url = f"https://{project_name}.pages.dev"
        try:
            # Resolve the domain's own zone (custom domains may live in a zone
            # other than the legacy global cf.zone_id). Only a genuine no-match
            # falls back to the global zone (the derived subdomain, which is
            # always in it); a transient CF error must NOT silently target the
            # wrong zone — let it propagate to dns_setup_failed.
            try:
                zone_id = await cf.resolve_zone_id(base_domain)
            except CloudflareZoneNotFoundError:
                # Falling back to the legacy global zone is only correct for a
                # domain that actually lives in it (the derived subdomain). A
                # custom domain with no resolvable zone must NOT get a CNAME in
                # the wrong (non-authoritative) zone — let it fail DNS setup.
                global_base = get_settings().site_base_domain
                if base_domain == global_base or base_domain.endswith(
                    f".{global_base}"
                ):
                    zone_id = cf.zone_id
                else:
                    raise
            dns_record = await setup_dns(base_domain, project_url, cf, zone_id)
        except Exception as e:
            dns_setup_failed = True
            logger.warning(
                "DNS setup failed", extra={"domain": base_domain, "error": str(e)}
            )

        try:
            await add_custom_domain(project_name, base_domain, cf)
            custom_domain = base_domain
        except Exception as e:
            domain_setup_failed = True
            logger.warning(
                "add custom domain failed, skipping",
                extra={"domain": base_domain, "error": str(e)},
            )

    return {
        "project_name": project_name,
        "pages_url": pages_url,
        "custom_domain": custom_domain,
        "dns_record": dns_record,
        "deployment_url": pages_url,
        "dns_setup_failed": dns_setup_failed,
        "domain_setup_failed": domain_setup_failed,
    }
