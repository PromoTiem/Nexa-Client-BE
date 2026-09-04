import copy
import json
import logging
import queue
from typing import Dict

from logging_loki import LokiQueueHandler
from logging_loki import emitter as loki_emitter

_LOG_RECORD_BUILTIN_ATTRS = {
    "args",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
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


class _NexaLokiEmitterV1(loki_emitter.LokiEmitterV1):
    def __call__(self, record: logging.LogRecord, line: str):
        payload = self.build_payload(record, line)
        resp = self.session.post(
            self.url,
            data=json.dumps(payload, ensure_ascii=False),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code != self.success_response_code:
            raise ValueError(
                "Unexpected Loki API response status code: {0}".format(resp.status_code)
            )


class NexaLokiHandler(LokiQueueHandler):
    """Async Loki handler with logfmt line formatting and UTF-8 safe JSON serialization."""

    def __init__(
        self,
        url: str,
        tags: Dict[str, str],
        level: int = logging.INFO,
        max_queue_size: int = 1024,
    ) -> None:
        q: queue.Queue = queue.Queue(maxsize=max_queue_size)
        super().__init__(q, url=url, tags=tags, version="1")
        self.handler.emitter = _NexaLokiEmitterV1(url=url, tags=tags)
        self.setLevel(level)

    def emit(self, record: logging.LogRecord) -> None:
        record = copy.copy(record)
        record.msg = _logfmt_line(record)
        record.args = None
        super().emit(record)
