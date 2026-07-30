from typing import Any, Callable, Dict, Optional

import httpx
from fastapi import HTTPException

from app.infrastructure.logging import get_logger
from app.infrastructure.retry_utils import execute_with_retry, make_retry_decorator

logger = get_logger("cloudflare")

_BASE_URL = "https://api.cloudflare.com/client/v4"


def _log_upstream_error(op: str, status: int, detail: str = "") -> None:
    logger.warning(
        "cloudflare upstream error",
        extra={"operation": op, "status": status, "detail": detail},
    )


def _extract_cf_errors(response: httpx.Response) -> str:
    try:
        body = response.json()
        errors = body.get("errors", [])
        return "; ".join(
            f"{e.get('code', '?')}: {e.get('message', '?')}" for e in errors
        )
    except Exception:
        return response.text[:500]


class CloudflareZoneNotFoundError(Exception):
    """No active Cloudflare zone in the account matches the given hostname."""

    def __init__(self, hostname: str) -> None:
        self.hostname = hostname
        super().__init__(f"No active zone found for host {hostname!r}")


class CloudflareConfigurationError(Exception):
    """Cloudflare client configuration is missing or invalid."""


class CloudflareClient:
    def __init__(
        self,
        api_token: str,
        account_id: str,
        zone_id: str = "",
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
    ) -> None:
        self._api_token = api_token
        self._account_id = account_id
        self._zone_id = zone_id
        self._base_url = _BASE_URL
        self._timeout = httpx.Timeout(
            connect=5.0, read=timeout, write=timeout, pool=5.0
        )
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff

    @property
    def api_token(self) -> str:
        return self._api_token

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def zone_id(self) -> str:
        return self._zone_id

    @property
    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._api_token}"}

    def _account_url(self, path: str) -> str:
        return f"{self._base_url}/accounts/{self._account_id}{path}"

    def _zone_url(self, zone_id: str, path: str) -> str:
        if not zone_id:
            raise CloudflareConfigurationError(
                "Cloudflare zone_id is not configured"
            )
        return f"{self._base_url}/zones/{zone_id}{path}"

    def _make_retry(self, op: str) -> Callable:
        return make_retry_decorator(
            max_retries=self._max_retries,
            backoff=self._retry_backoff,
            max_jitter=15,
            service="cloudflare",
            extra_context=f"cloudflare:{op}",
        )

    async def _execute_with_retry(
        self,
        retry_decorator: Callable,
        request_fn: Callable,
    ) -> httpx.Response:
        return await execute_with_retry(retry_decorator, request_fn)

    def _handle_errors(
        self, response: httpx.Response, op: str
    ) -> Dict[str, Any]:
        if response.is_success:
            return response.json()

        detail = _extract_cf_errors(response)
        status = response.status_code

        if status == 400:
            raise HTTPException(status_code=400, detail=detail or "Bad request")
        if status == 401:
            raise HTTPException(
                status_code=401, detail="Invalid Cloudflare credentials"
            )
        if status == 403:
            raise HTTPException(
                status_code=403, detail="Cloudflare permission denied"
            )
        if status == 404:
            raise HTTPException(status_code=404, detail=detail or "Not found")
        if status == 409:
            raise HTTPException(
                status_code=409, detail=detail or "Conflict"
            )
        if status == 429:
            raise HTTPException(
                status_code=429, detail="Cloudflare rate limit exceeded"
            )

        _log_upstream_error(op, status, detail)
        raise HTTPException(
            status_code=status, detail="Cloudflare API error"
        )

    async def create_project(
        self,
        name: str,
        production_branch: str = "main",
    ) -> Dict[str, Any]:
        url = self._account_url("/pages/projects")
        payload = {
            "name": name,
            "production_branch": production_branch,
        }

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.post(
                    url, json=payload, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("create_project"), _do_request
        )
        return self._handle_errors(response, "create_project")

    async def get_project(self, name: str) -> Dict[str, Any]:
        url = self._account_url(f"/pages/projects/{name}")

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("get_project"), _do_request
        )
        return self._handle_errors(response, "get_project")

    async def list_projects(self) -> Dict[str, Any]:
        url = self._account_url("/pages/projects")

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("list_projects"), _do_request
        )
        return self._handle_errors(response, "list_projects")

    async def list_zones(self, status: str = "active") -> Dict[str, Any]:
        url = f"{self._base_url}/zones"
        page = 1
        zones = []
        combined_response: Optional[Dict[str, Any]] = None

        while True:
            params = {
                "account.id": self._account_id,
                "status": status,
                "page": page,
                "per_page": 50,
            }

            async def _do_request() -> httpx.Response:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    return await client.get(
                        url, params=params, headers=self._auth_headers
                    )

            response = await self._execute_with_retry(
                self._make_retry("list_zones"), _do_request
            )
            page_response = self._handle_errors(response, "list_zones")
            if combined_response is None:
                combined_response = page_response
            zones.extend(page_response.get("result", []))

            result_info = page_response.get("result_info", {})
            total_pages = int(result_info.get("total_pages", page))
            if page >= total_pages:
                combined_response["result"] = zones
                combined_info = dict(
                    combined_response.get("result_info", {})
                )
                if combined_info:
                    combined_info["page"] = 1
                    combined_info["count"] = len(zones)
                    combined_response["result_info"] = combined_info
                return combined_response
            page += 1

    async def resolve_zone_id(self, domain_name: str) -> str:
        hostname = domain_name.lower().rstrip(".")
        response = await self.list_zones(status="active")
        matches = [
            z for z in response.get("result", [])
            if hostname == z["name"] or hostname.endswith(f'.{z["name"]}')
        ]
        if not matches:
            raise CloudflareZoneNotFoundError(hostname)
        return max(matches, key=lambda z: len(z["name"]))["id"]

    async def delete_project(self, name: str) -> Dict[str, Any]:
        url = self._account_url(f"/pages/projects/{name}")

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.delete(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("delete_project"), _do_request
        )
        return self._handle_errors(response, "delete_project")

    async def add_domain(
        self, project_name: str, domain_name: str
    ) -> Dict[str, Any]:
        url = self._account_url(
            f"/pages/projects/{project_name}/domains"
        )
        payload = {"name": domain_name}

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.post(
                    url, json=payload, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("add_domain"), _do_request
        )
        return self._handle_errors(response, "add_domain")

    async def get_domain(
        self, project_name: str, domain_name: str
    ) -> Dict[str, Any]:
        url = self._account_url(
            f"/pages/projects/{project_name}/domains/{domain_name}"
        )

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("get_domain"), _do_request
        )
        return self._handle_errors(response, "get_domain")

    async def list_domains(
        self, project_name: str
    ) -> Dict[str, Any]:
        url = self._account_url(
            f"/pages/projects/{project_name}/domains"
        )

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("list_domains"), _do_request
        )
        return self._handle_errors(response, "list_domains")

    async def delete_domain(
        self, project_name: str, domain_name: str
    ) -> Dict[str, Any]:
        url = self._account_url(
            f"/pages/projects/{project_name}/domains/{domain_name}"
        )

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.delete(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("delete_domain"), _do_request
        )
        return self._handle_errors(response, "delete_domain")

    async def create_dns_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        proxied: bool = True,
        ttl: int = 1,
    ) -> Dict[str, Any]:
        url = self._zone_url(zone_id, "/dns_records")
        payload = {
            "type": record_type,
            "name": name,
            "content": content,
            "proxied": proxied,
            "ttl": ttl,
        }

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.post(
                    url, json=payload, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("create_dns_record"),
            _do_request,
        )
        return self._handle_errors(response, "create_dns_record")

    async def list_dns_records(
        self,
        zone_id: str,
        record_type: Optional[str] = None,
        name: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        url = self._zone_url(zone_id, "/dns_records")
        params: Dict[str, Any] = {"page": page, "per_page": per_page}
        if record_type:
            params["type"] = record_type
        if name:
            params["name"] = name

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(
                    url, params=params, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("list_dns_records"),
            _do_request,
        )
        return self._handle_errors(response, "list_dns_records")

    async def delete_dns_record(self, zone_id: str, record_id: str) -> Dict[str, Any]:
        url = self._zone_url(zone_id, f"/dns_records/{record_id}")

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.delete(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("delete_dns_record"),
            _do_request,
        )
        return self._handle_errors(response, "delete_dns_record")

    async def list_tunnels(self) -> Dict[str, Any]:
        url = self._account_url("/cfd_tunnel")

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("list_tunnels"),
            _do_request,
        )
        return self._handle_errors(response, "list_tunnels")

    async def delete_tunnel(self, tunnel_id: str) -> Dict[str, Any]:
        url = self._account_url(f"/cfd_tunnel/{tunnel_id}")

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.delete(
                    url, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("delete_tunnel"),
            _do_request,
        )
        return self._handle_errors(response, "delete_tunnel")

    async def verify_domain_ownership(
        self, zone_id: str, domain_name: str
    ) -> Dict[str, Any]:
        url = self._zone_url(zone_id, "/dns_records")
        params = {"type": "TXT", "name": domain_name}

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(
                    url, params=params, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("verify_domain_ownership"),
            _do_request,
        )
        return self._handle_errors(response, "verify_domain_ownership")

    async def create_verification_record(
        self, zone_id: str, domain_name: str, token: str
    ) -> Dict[str, Any]:
        url = self._zone_url(zone_id, "/dns_records")
        payload = {
            "type": "TXT",
            "name": domain_name,
            "content": token,
            "ttl": 1,
        }

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.post(
                    url, json=payload, headers=self._auth_headers
                )

        response = await self._execute_with_retry(
            self._make_retry("create_verification_record"),
            _do_request,
        )
        return self._handle_errors(response, "create_verification_record")


