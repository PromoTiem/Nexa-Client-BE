import httpx

from app.config import get_settings
from app.infrastructure.logging import get_logger

logger = get_logger("telegram")

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram_message(text: str, parse_mode: str = "Markdown") -> bool:
    settings = get_settings()
    if not settings.telegram_enabled:
        return False

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram bot token or chat ID not configured")
        return False

    url = TELEGRAM_API_URL.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    if settings.telegram_thread_id:
        payload["message_thread_id"] = int(settings.telegram_thread_id)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Telegram message sent successfully")
            return True
    except httpx.HTTPStatusError as e:
        logger.error("Telegram API HTTP error: %s — %s",
                     e.response.status_code, e.response.text)
        return False
    except httpx.RequestError as e:
        logger.error("Telegram API request error: %s", str(e))
        return False
    except Exception as e:
        logger.error("Unexpected error sending Telegram message: %s", str(e))
        return False
