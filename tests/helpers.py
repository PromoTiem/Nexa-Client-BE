import os

from app.config import get_settings


async def get_live_token_or_skip() -> str | None:
    token = os.environ.get("LIVE_AUTH_TOKEN", "")
    if token:
        return token
    settings = get_settings()
    if not settings.test_identity or not settings.test_password:
        return None
    from app.infrastructure.pocketbase.client import PocketBaseClient

    pb = PocketBaseClient(base_url=settings.pocketbase_url)
    try:
        result = await pb.auth_with_password(
            collection=settings.pocketbase_auth_collection,
            identity=settings.test_identity,
            password=settings.test_password,
        )
        return result["token"]
    except Exception:
        return None


async def cleanup_record(live_client, token: str, path: str) -> None:
    try:
        await live_client.delete(
            path,
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        pass
