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


async def _admin_pb_client():
    """Build a PocketBase client authed as superuser for background tasks.

    The collector flush and daily scheduler run without a request context,
    so they cannot use per-request user tokens. Without a token the PB
    client raises 401 before any HTTP call and background writes silently
    fail — events are dropped and aggregates are never persisted.
    """
    from app.infrastructure.pocketbase.client import PocketBaseClient

    pb = PocketBaseClient(
        base_url=settings.pocketbase_url,
        timeout=settings.pocketbase_timeout,
        max_retries=settings.pocketbase_max_retries,
        retry_backoff=settings.pocketbase_retry_backoff,
    )
    if not settings.pocketbase_admin_email or not settings.pocketbase_admin_password:
        logger.warning(
            "PB admin credentials unset; analytics background writes disabled"
        )
        return pb
    try:
        auth = await pb.auth_admin(
            settings.pocketbase_admin_email,
            settings.pocketbase_admin_password,
        )
        token = auth.get("token", "")
        if not token:
            raise ValueError("empty admin token")
        return PocketBaseClient(
            base_url=settings.pocketbase_url,
            timeout=settings.pocketbase_timeout,
            max_retries=settings.pocketbase_max_retries,
            retry_backoff=settings.pocketbase_retry_backoff,
            static_token=token,
        )
    except Exception as e:
        logger.error(
            "PB admin auth failed; analytics background writes disabled",
            extra={"error": str(e)},
        )
        return pb


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start analytics collector if enabled
    if settings.analytics.aggregation_enabled:
        from app.infrastructure.analytics.collector import AnalyticsCollector

        pb = await _admin_pb_client()
        collector = AnalyticsCollector(
            pb=pb,
            buffer_size=settings.analytics.buffer_size,
            flush_interval=settings.analytics.flush_interval_seconds,
        )
        await collector.start()
        app.state.analytics_collector = collector

    # Start daily aggregation scheduler if enabled
    if settings.analytics.daily_aggregation_enabled:
        from app.infrastructure.analytics.scheduler import DailyAggregationScheduler

        scheduler_pb = await _admin_pb_client()
        scheduler = DailyAggregationScheduler(
            pb=scheduler_pb,
            aggregation_hour=settings.analytics.daily_aggregation_hour,
            retention_days=settings.analytics.retention_days,
        )
        await scheduler.start()
        app.state.analytics_scheduler = scheduler

    logger.info("client api started")
    yield

    # Stop analytics scheduler
    if hasattr(app.state, "analytics_scheduler"):
        await app.state.analytics_scheduler.stop()

    # Stop analytics collector
    if hasattr(app.state, "analytics_collector"):
        await app.state.analytics_collector.stop()

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
