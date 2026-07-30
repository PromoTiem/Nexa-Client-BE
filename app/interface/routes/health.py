from fastapi import APIRouter

from app.config import get_settings
from app.interface.dto.health import HealthResponse

router = APIRouter()
settings = get_settings()


@router.get("", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        env=settings.app_env,
    )
