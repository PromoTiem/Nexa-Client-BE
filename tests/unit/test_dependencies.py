import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException

from app.interface.dependencies import AuthContext, get_auth_context
from app.config import Settings


MOCK_RECORD = {
    "id": "user_123",
    "email": "test@example.com",
    "tenant_id": "tenant_abc",
    "role": "admin",
}

MOCK_AUTH_DATA = {
    "token": "valid.token.here",
    "record": MOCK_RECORD,
}


class TestGetAuthContext:
    @pytest.mark.asyncio
    async def test_valid_token_returns_auth_context(self):
        mock_pb = AsyncMock()
        mock_pb.auth_refresh = AsyncMock(return_value=MOCK_AUTH_DATA)

        mock_credentials = type(
            "Creds", (), {"credentials": "valid.token.here"}
        )()

        settings = Settings()

        auth = await get_auth_context(
            credentials=mock_credentials,
            settings=settings,
            pb=mock_pb,
        )

        assert isinstance(auth, AuthContext)
        assert auth.token == "valid.token.here"
        assert auth.record["email"] == "test@example.com"
        assert auth.record["tenant_id"] == "tenant_abc"

    @pytest.mark.asyncio
    async def test_missing_token_raises_401(self):
        mock_pb = AsyncMock()
        settings = Settings()

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(
                credentials=None,
                settings=settings,
                pb=mock_pb,
            )

        assert exc_info.value.status_code == 401
        assert "Missing authorization token" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_user_without_tenant_id_raises_403(self):
        mock_pb = AsyncMock()
        mock_pb.auth_refresh = AsyncMock(
            return_value={
                "token": "valid.token.here",
                "record": {"id": "user_123", "email": "test@example.com"},
            }
        )

        mock_credentials = type(
            "Creds", (), {"credentials": "valid.token.here"}
        )()

        settings = Settings()

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(
                credentials=mock_credentials,
                settings=settings,
                pb=mock_pb,
            )

        assert exc_info.value.status_code == 403
        assert "tenant_id" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        mock_pb = AsyncMock()
        mock_pb.auth_refresh = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="Invalid token")
        )

        mock_credentials = type(
            "Creds", (), {"credentials": "expired.token"}
        )()

        settings = Settings()

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(
                credentials=mock_credentials,
                settings=settings,
                pb=mock_pb,
            )

        assert exc_info.value.status_code == 401
