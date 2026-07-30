import sys
from pathlib import Path

from app.config import get_settings
from app.infrastructure.logging import get_logger

logger = get_logger("run")

SCRIPTS_DIR = Path(__file__).parent / "scripts"

settings = get_settings()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.is_development,
)
