"""HTTP acceptance with reset-mail dispatch mocked; no SMTP or tokens emitted."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.interface.dependencies import get_pocketbase_client
from app.interface.limiter import limiter
from app.interface.routes.auth import router


@pytest.fixture
async def reset_api():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router, prefix="/auth")
    mail = AsyncMock(return_value=None)
    app.dependency_overrides[get_pocketbase_client] = lambda: SimpleNamespace(
        request_password_reset=mail
    )
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        pocketbase_auth_collection="users"
    )
    limiter.reset()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, mail
    finally:
        limiter.reset()


async def test_existing_and_missing_accounts_have_identical_acknowledgement(reset_api):
    client, mail = reset_api
    known = await client.post(
        "/auth/forgot-password", json={"email": "known@example.com"}
    )
    missing = await client.post(
        "/auth/forgot-password", json={"email": "missing@example.com"}
    )
    assert known.status_code == missing.status_code == 200
    assert (
        known.json()
        == missing.json()
        == {
            "message": "If the account exists, password reset instructions will be emailed."
        }
    )
    assert mail.await_count == 2
    mail.assert_any_await("users", "known@example.com")
    mail.assert_any_await("users", "missing@example.com")


async def test_invalid_email_never_dispatches(reset_api):
    client, mail = reset_api
    response = await client.post("/auth/forgot-password", json={"email": "invalid"})
    assert response.status_code == 422
    mail.assert_not_awaited()


async def test_mail_service_failure_is_not_reported_as_sent(reset_api):
    client, mail = reset_api
    mail.side_effect = HTTPException(503, "Password recovery unavailable")
    response = await client.post(
        "/auth/forgot-password", json={"email": "known@example.com"}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Password recovery unavailable"}


async def test_reset_limit_blocks_fourth_dispatch(reset_api):
    client, mail = reset_api
    responses = [
        await client.post("/auth/forgot-password", json={"email": "known@example.com"})
        for _ in range(4)
    ]
    assert [response.status_code for response in responses] == [200, 200, 200, 429]
    assert mail.await_count == 3
