from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException

from app.infrastructure.logging import get_logger
from app.infrastructure.retry_utils import execute_with_retry, make_retry_decorator

logger = get_logger("pocketbase")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _log_upstream_error(op: str, collection: str, status: int) -> None:
    logger.warning(
        "pocketbase upstream error",
        extra={"operation": op, "collection": collection, "status": status},
    )


def _format_pb_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        return response.text[:500] or f"HTTP {response.status_code}"
    message = body.get("message", "Validation error")
    data = body.get("data")
    if data:
        field_errors = [
            f"{field}: {info.get('message', info.get('code', 'unknown'))}"
            for field, info in data.items()
            if isinstance(info, dict)
        ]
        if field_errors:
            message += " (" + "; ".join(field_errors) + ")"
    return message


class PocketBaseClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
        static_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(connect=5.0, read=timeout, write=10.0, pool=5.0)
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._static_token = static_token

    def _get_auth_headers(self, token: str | None = None) -> dict[str, str]:
        if token:
            return {"Authorization": token}
        if self._static_token:
            return {"x_api_be_token": self._static_token}
        raise HTTPException(
            status_code=401,
            detail="No token provided and no static token set",
        )

    def _make_retry(self, op: str, collection: str) -> Callable:
        return make_retry_decorator(
            max_retries=self._max_retries,
            backoff=self._retry_backoff,
            max_jitter=10,
            service="pocketbase",
            extra_context=f"pocketbase:{collection}:{op}",
        )

    async def _execute_with_retry(
        self,
        retry_decorator: Callable,
        request_fn: Callable,
    ) -> httpx.Response:
        return await execute_with_retry(retry_decorator, request_fn)

    def _handle_response(
        self,
        response: httpx.Response,
        op: str,
        collection: str,
        *,
        allow_400: bool = False,
        not_found_detail: str = "Record not found",
    ) -> dict[str, Any] | None:
        """Handle PocketBase HTTP response, raising appropriate exceptions on error."""
        if response.is_success:
            if response.status_code == 204:
                return None
            try:
                return response.json()
            except Exception:
                raise HTTPException(
                    status_code=502,
                    detail="Invalid response from PocketBase",
                )
        if response.status_code == 400 and not allow_400:
            raise HTTPException(status_code=400, detail=_format_pb_error(response))
        if response.status_code == 404:
            _log_upstream_error(op, collection, response.status_code)
        raise HTTPException(
            status_code=response.status_code, detail=_format_pb_error(response)
        )

    async def auth_with_password(
        self,
        collection: str,
        identity: str,
        password: str,
        identity_field: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/api/collections/{collection}/auth-with-password"
        payload: dict[str, Any] = {"identity": identity, "password": password}
        if identity_field:
            payload["identityField"] = identity_field

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.post(url, json=payload)

        response = await self._execute_with_retry(
            self._make_retry("auth", collection),
            _do_request,
        )
        if response.status_code == 400:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return self._handle_response(
            response, "auth", collection, not_found_detail="Auth collection not found"
        )

    async def auth_refresh(
        self,
        collection: str,
        token: str,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/api/collections/{collection}/auth-refresh"

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.post(
                    url,
                    headers={
                        "Authorization": token,
                        "Content-Type": "application/json",
                    },
                    json={},
                )

        response = await self._execute_with_retry(
            self._make_retry("auth_refresh", collection),
            _do_request,
        )
        if response.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token",
            )
        return self._handle_response(
            response,
            "auth_refresh",
            collection,
            not_found_detail="Auth collection not found",
        )

    async def auth_admin(
        self,
        email: str,
        password: str,
    ) -> Dict[str, Any]:
        url = f"{self._base_url}/api/admins/auth-with-password"
        payload = {"identity": email, "password": password}

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.post(url, json=payload)

        response = await self._execute_with_retry(
            self._make_retry("auth_admin", "_admins"), _do_request,
        )
        if response.status_code == 400:
            raise HTTPException(status_code=401, detail="Invalid admin credentials")
        return self._handle_response(
            response, "auth_admin", "_admins", not_found_detail="Admin auth failed"
        )


    async def list_records(
        self,
        collection: str,
        token: str | None = None,
        filter: str | None = None,
        sort: str | None = None,
        page: int = 1,
        per_page: int = 50,
        expand: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/api/collections/{collection}/records"
        params: dict[str, Any] = {"page": page, "perPage": per_page}
        if filter:
            params["filter"] = filter
        if sort:
            params["sort"] = sort
        if expand:
            params["expand"] = expand

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(
                    url, params=params, headers=self._get_auth_headers(token)
                )

        response = await self._execute_with_retry(
            self._make_retry("list", collection),
            _do_request,
        )
        return self._handle_response(
            response,
            "list",
            collection,
            not_found_detail=f"Collection '{collection}' not found",
        )

    async def collection_list(
        self,
        collection: str,
        token: str | None = None,
        filter_expr: str | None = None,
        sort: str | None = None,
        page: int = 1,
        per_page: int = 50,
        expand: str | None = None,
    ) -> dict[str, Any]:
        """Alias for list_records using filter_expr parameter name."""
        return await self.list_records(
            collection=collection,
            token=token,
            filter=filter_expr,
            sort=sort,
            page=page,
            per_page=per_page,
            expand=expand,
        )

    async def find_one_by_filter(
        self,
        collection: str,
        filter_expr: str,
        token: str | None = None,
        expand: str | None = None,
    ) -> dict[str, Any]:
        result = await self.list_records(
            collection=collection,
            token=token,
            filter=filter_expr,
            page=1,
            per_page=1,
            expand=expand,
        )
        items: list[dict[str, Any]] = result.get("items", [])
        if not items:
            raise HTTPException(status_code=404, detail="Record not found")
        return items[0]

    async def find_record_by_id(
        self,
        collection: str,
        record_id: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/api/collections/{collection}/records/{record_id}"

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(url, headers=self._get_auth_headers(token))

        response = await self._execute_with_retry(
            self._make_retry("get_by_id", collection),
            _do_request,
        )
        return self._handle_response(response, "get_by_id", collection)

    async def create_record(
        self,
        collection: str,
        data: dict[str, Any],
        token: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/api/collections/{collection}/records"
        now = _now_iso()
        payload = dict(data)
        payload["created_at"] = now
        payload["updated_at"] = now
        if user_id:
            payload["created_by"] = user_id
            payload["updated_by"] = user_id

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.post(
                    url, json=payload, headers=self._get_auth_headers(token)
                )

        response = await self._execute_with_retry(
            self._make_retry("create", collection),
            _do_request,
        )
        return self._handle_response(response, "create", collection)

    async def update_record(
        self,
        collection: str,
        record_id: str,
        data: dict[str, Any],
        token: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/api/collections/{collection}/records/{record_id}"
        payload = dict(data)
        payload["updated_at"] = _now_iso()
        if user_id:
            payload["updated_by"] = user_id

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.patch(
                    url, json=payload, headers=self._get_auth_headers(token)
                )

        response = await self._execute_with_retry(
            self._make_retry("update", collection),
            _do_request,
        )
        return self._handle_response(response, "update", collection)

    async def delete_record(
        self,
        collection: str,
        record_id: str,
        token: str | None = None,
    ) -> None:
        url = f"{self._base_url}/api/collections/{collection}/records/{record_id}"

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.delete(url, headers=self._get_auth_headers(token))

        response = await self._execute_with_retry(
            self._make_retry("delete", collection),
            _do_request,
        )
        self._handle_response(response, "delete", collection)


def create_static_pb_client(
    base_url: str | None = None,
    static_token: str | None = None,
    timeout: float = 10.0,
    max_retries: int = 3,
    retry_backoff: float = 0.5,
    *,
    settings: Any = None,
) -> PocketBaseClient:
    """Create a PocketBaseClient with a static API token for background tasks.

    Accepts either explicit params or a settings object with pocketbase_* attrs.
    """
    if settings is not None:
        base_url = base_url or settings.pocketbase_url
        timeout = getattr(settings, "pocketbase_timeout", timeout)
        max_retries = getattr(settings, "pocketbase_max_retries", max_retries)
        retry_backoff = getattr(settings, "pocketbase_retry_backoff", retry_backoff)
    if not base_url or not static_token:
        raise ValueError("base_url and static_token are required")
    return PocketBaseClient(
        base_url=base_url,
        static_token=static_token,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
    )
