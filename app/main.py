from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings
from app.infrastructure.logging import configure_logging, get_logger
from app.interface.exception_handlers import register_exception_handlers
from app.interface.middlewares.access_log import AccessLogMiddleware
from app.interface.middlewares.dynamic_cors import DynamicCORSMiddleware
from app.interface.routes import router

logger = get_logger("main")

settings = get_settings()
configure_logging(settings)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("client api started")
    yield
    logger.info("client api stopped")


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

register_exception_handlers(app)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(
    DynamicCORSMiddleware,
    allowed_origins=settings.cors_origins,
    site_base_domain=settings.site_base_domain,
    restrict_http_origins=not settings.is_development,
)

app.include_router(router)
