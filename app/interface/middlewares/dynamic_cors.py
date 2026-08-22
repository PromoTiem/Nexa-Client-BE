from typing import List

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """CORS middleware that dynamically allows origins matching site base domains."""

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: List[str] = None,
        site_base_domain: str = "",
        allow_credentials: bool = True,
        allow_methods: List[str] = None,
        allow_headers: List[str] = None,
    ) -> None:
        super().__init__(app)
        self.allowed_origins = set(allowed_origins or [])
        self.site_base_domain = site_base_domain
        self.allow_credentials = allow_credentials
        self.allow_methods = allow_methods or ["*"]
        self.allow_headers = allow_headers or ["*"]

    def _is_origin_allowed(self, origin: str) -> bool:
        if origin in self.allowed_origins:
            return True
        if self.site_base_domain:
            if origin.startswith("https://") and origin.endswith(f".{self.site_base_domain}"):
                return True
            if origin.startswith("http://") and origin.endswith(f".{self.site_base_domain}"):
                return True
        return False

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        origin = request.headers.get("origin")

        if request.method == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)

        if origin and self._is_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = ", ".join(self.allow_methods)
            response.headers["Access-Control-Allow-Headers"] = ", ".join(self.allow_headers)
            response.headers["Access-Control-Max-Age"] = "86400"

        return response
