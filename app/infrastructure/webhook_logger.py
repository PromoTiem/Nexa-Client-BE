import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

from app.infrastructure.webhook_utils import extract_webhook_metadata

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_FILE = _LOG_DIR / "webhook_payloads.log"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _create_logger() -> logging.Logger:
    _ensure_log_dir()
    logger = logging.getLogger("nexa.webhook.payloads")  # dedicated file-only logger, intentionally not using get_logger()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            _LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


_webhook_logger = _create_logger()


def log_webhook_event(
    event_type: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
) -> None:
    action, repo, sender = extract_webhook_metadata(payload)
    entry = {
        "event": event_type,
        "action": action,
        "repo": repo,
        "sender": sender,
        "headers": headers,
        "payload": payload,
    }
    _webhook_logger.info(json.dumps(entry, default=str))
