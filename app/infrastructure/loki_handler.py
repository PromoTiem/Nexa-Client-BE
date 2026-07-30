import copy
import logging
import queue
from typing import Dict

from logging_loki import LokiQueueHandler

_LOG_RECORD_BUILTIN_ATTRS = {
    "args", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module",
    "msecs", "message", "msg", "name", "pathname", "process",
    "processName", "relativeCreated", "stack_info", "thread",
    "threadName", "taskName",
}


def _logfmt_line(record: logging.LogRecord) -> str:
    parts = []
    for key, value in record.__dict__.items():
        if key in _LOG_RECORD_BUILTIN_ATTRS:
            continue
        if key.startswith("_"):
            continue
        if value is None:
            continue
        s = str(value)
        if " " in s or "=" in s:
            s = f'"{s}"'
        parts.append(f"{key}={s}")
    return " ".join(parts)


class NexaLokiHandler(LokiQueueHandler):
    """Async Loki handler with logfmt line formatting.

    Wraps LokiQueueHandler to:
    - Deliver log records asynchronously via a queue (non-blocking).
    - Format extra dicts as logfmt lines for structured Loki queries.
    """

    def __init__(
        self,
        url: str,
        tags: Dict[str, str],
        level: int = logging.INFO,
        max_queue_size: int = 1024,
    ) -> None:
        q: queue.Queue = queue.Queue(maxsize=max_queue_size)
        super().__init__(q, url=url, tags=tags, version="1")
        self.setLevel(level)

    def emit(self, record: logging.LogRecord) -> None:
        # Copy the record so we don't mutate the shared object for other handlers.
        record = copy.copy(record)
        record.msg = _logfmt_line(record)
        record.args = None
        super().emit(record)
