import logging
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.infrastructure.cloudflare.client import CloudflareConfigurationError
from app.infrastructure.logging import get_logger

logger = get_logger("errors")


def _extract_client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    status = exc.status_code
    level = logging.ERROR if status >= 500 else logging.WARNING

    logger.log(
        level,
        "http error",
        extra={
            "method": request.method,
            "path": str(request.url.path),
            "status": status,
            "detail": str(exc.detail),
            "client_ip": _extract_client_ip(request),
        },
    )

    return JSONResponse(
        status_code=status,
        content={"detail": exc.detail},
    )


async def cloudflare_configuration_exception_handler(
    request: Request, exc: CloudflareConfigurationError
) -> JSONResponse:
    return await http_exception_handler(
        request,
        HTTPException(status_code=500, detail=str(exc)),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    error_summary = [
        {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in errors
    ]

    logger.warning(
        "validation error",
        extra={
            "method": request.method,
            "path": str(request.url.path),
            "status": 422,
            "errors": error_summary,
            "client_ip": _extract_client_ip(request),
        },
    )

    return JSONResponse(
        status_code=422,
        content={"detail": "Validation error", "errors": error_summary},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tb_text = "".join(tb)

    logger.error(
        "unhandled exception",
        extra={
            "method": request.method,
            "path": str(request.url.path),
            "status": 500,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": tb_text,
            "client_ip": _extract_client_ip(request),
        },
    )

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        CloudflareConfigurationError,
        cloudflare_configuration_exception_handler,
    )
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
