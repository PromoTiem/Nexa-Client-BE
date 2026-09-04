import httpx
import pytest

from app.config import get_settings
from app.main import app


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def live_client():
    settings = get_settings()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=settings.pocketbase_url,
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()
