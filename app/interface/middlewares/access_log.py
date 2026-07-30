import logging
import time

from app.infrastructure.logging import get_logger

logger = get_logger("access")


class AccessLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500
        path = scope.get("path", "")
        method = scope.get("method", "")
        query_string = scope.get("query_string", b"")
        client = scope.get("client")
        client_ip = f"{client[0]}:{client[1]}" if client else "unknown"
        exception_info = None

        async def _send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        except Exception as exc:
            exception_info = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            level = logging.WARNING if status_code >= 400 else logging.INFO

            if query_string:
                path += f"?{query_string.decode('utf-8', errors='replace')}"

            extra = {
                "method": method,
                "path": path,
                "status": status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": client_ip,
            }
            if exception_info:
                extra["exception"] = exception_info

            logger.log(
                level,
                "http request",
                extra=extra,
            )
