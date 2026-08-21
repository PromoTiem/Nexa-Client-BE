from fastapi import APIRouter

from app.interface.routes.auth import router as auth_router
from app.interface.routes.build import router as build_router
from app.interface.routes.health import router as health_router
from app.interface.routes.site import router as site_router
from app.interface.routes.serve import router as serve_router
from app.interface.routes.property import router as property_router
from app.interface.routes.template import router as template_router
from app.interface.routes.style import router as style_router
from app.interface.routes.block import router as block_router
from app.interface.routes.page import router as page_router
from app.interface.routes.section import router as section_router
from app.interface.routes.media import router as media_router
from app.interface.routes.storage import router as storage_router
from app.interface.routes.user import router as user_router

router = APIRouter()

router.include_router(health_router, prefix="/health", tags=["health"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(user_router, prefix="/users", tags=["user"])
router.include_router(site_router, prefix="/sites", tags=["site"])
router.include_router(build_router, prefix="/builds", tags=["build"])
router.include_router(serve_router, prefix="/sites", tags=["serve"])
router.include_router(property_router, tags=["property"])
router.include_router(template_router, prefix="/templates", tags=["template"])
router.include_router(style_router, prefix="/styles", tags=["style"])
router.include_router(block_router, prefix="/blocks", tags=["block"])
router.include_router(page_router, prefix="/pages", tags=["page"])
router.include_router(section_router, prefix="/sections", tags=["section"])
router.include_router(media_router, prefix="/media", tags=["media"])
router.include_router(storage_router, prefix="/storage", tags=["storage"])
