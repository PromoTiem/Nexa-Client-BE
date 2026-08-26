import logging

from pythonjsonlogger.json import JsonFormatter

from app.config import LoggingSettings, Settings

_CONFIGURED = False
_NEXA_LOGGER = "nexa"
_LOKI_HANDLER_NAME = "nexa.loki"
_CONSOLE_HANDLER_NAME = "nexa.console"

_JSON_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _resolve_level(level: str) -> int:
    return _LEVEL_MAP.get((level or "").upper(), logging.INFO)


def _is_named_handler(handler: logging.Handler, name: str) -> bool:
    return getattr(handler, "_nexa_name", None) == name


def _remove_named_handlers(logger: logging.Logger, name: str) -> None:
    for handler in list(logger.handlers):
        if _is_named_handler(handler, name):
            logger.removeHandler(handler)


def configure_logging(settings: Settings) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_cfg: LoggingSettings = settings.logging
    level = _resolve_level(log_cfg.level)

    # Quiet noisy third-party loggers
    if level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Configure the nexa logger hierarchy
    nexa = logging.getLogger(_NEXA_LOGGER)
    nexa.setLevel(level)
    nexa.propagate = False

    # Remove stale handlers (idempotent reconfigure)
    _remove_named_handlers(nexa, _LOKI_HANDLER_NAME)

    # Loki handler only - nexa logs go to Loki, NOT to console
    if log_cfg.loki_enabled:
        try:
            from app.infrastructure.loki_handler import NexaLokiHandler
        except ImportError:
            nexa.warning(
                "logging.loki_enabled is true but python-logging-loki "
                "is not installed; loki handler skipped"
            )
        else:
            tags = dict(log_cfg.loki_labels)
            tags.setdefault("app", settings.app_name)
            loki = NexaLokiHandler(
                url=log_cfg.loki_url,
                tags=tags,
                level=level,
            )
            loki._nexa_name = _LOKI_HANDLER_NAME
            loki.setFormatter(
                JsonFormatter(
                    fmt=_JSON_FORMAT,
                    rename_fields={"levelname": "level", "name": "logger"},
                    json_ensure_ascii=False,
                )
            )
            nexa.addHandler(loki)

    # Console fallback — when Loki is disabled, send nexa logs to stderr
    if not log_cfg.loki_enabled:
        console = logging.StreamHandler()
        console.setLevel(level)
        console._nexa_name = _CONSOLE_HANDLER_NAME
        console.setFormatter(
            JsonFormatter(
                fmt=_JSON_FORMAT,
                rename_fields={"levelname": "level", "name": "logger"},
                json_ensure_ascii=False,
            )
        )
        nexa.addHandler(console)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> logging.Logger:
    if name is None:
        return logging.getLogger(_NEXA_LOGGER)
    return logging.getLogger(f"{_NEXA_LOGGER}.{name}")


def reset_for_testing() -> None:
    global _CONFIGURED
    _CONFIGURED = False
    nexa = logging.getLogger(_NEXA_LOGGER)
    _remove_named_handlers(nexa, _LOKI_HANDLER_NAME)
    _remove_named_handlers(nexa, _CONSOLE_HANDLER_NAME)
