from fastapi import APIRouter

from app.interface.routes.auth import router as auth_router
from app.interface.routes.health import router as health_router
from app.interface.routes.site import router as site_router
from app.interface.routes.property import router as property_router
from app.interface.routes.media import router as media_router
from app.interface.routes.storage import router as storage_router

router = APIRouter()

router.include_router(health_router, prefix="/health", tags=["health"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(site_router, prefix="/sites", tags=["site"])
router.include_router(property_router, tags=["property"])
router.include_router(media_router, prefix="/media", tags=["media"])
router.include_router(storage_router, prefix="/storage", tags=["storage"])
