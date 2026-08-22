from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.infrastructure.logging import configure_logging, get_logger
from app.interface.exception_handlers import register_exception_handlers
from app.interface.middlewares.access_log import AccessLogMiddleware
from app.interface.middlewares.dynamic_cors import DynamicCORSMiddleware
from app.interface.routes import router

logger = get_logger("main")

settings = get_settings()
configure_logging(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("client api started")
    yield
    logger.info("client api stopped")


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

register_exception_handlers(app)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(
    DynamicCORSMiddleware,
    allowed_origins=settings.cors_origins,
    site_base_domain=settings.site_base_domain,
)

app.include_router(router)
