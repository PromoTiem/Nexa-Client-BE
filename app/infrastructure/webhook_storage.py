import json

from app.config import get_settings
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import create_static_pb_client
from app.infrastructure.webhook_utils import extract_webhook_metadata

logger = get_logger("webhook_storage")

WEBHOOKS_COLLECTION = "webhooks"


async def store_webhook(
    event_type: str,
    payload: dict,
    headers: dict,
) -> None:
    try:
        settings = get_settings()
        client = create_static_pb_client(settings=settings)

        action, repo, sender = extract_webhook_metadata(payload)

        data = {
            "event_type": event_type,
            "action": action,
            "repo": repo,
            "sender": sender,
            "payload": json.dumps(payload, default=str),
            "headers": json.dumps(headers, default=str),
        }

        await client.create_record(
            collection=WEBHOOKS_COLLECTION,
            data=data,
        )
        logger.info("webhook stored in pocketbase", extra={"event_type": event_type})
    except Exception as e:
        logger.error("failed to store webhook in pocketbase", extra={"error": str(e)})
