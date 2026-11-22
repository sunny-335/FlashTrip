"""structlog JSON 日志 + 密钥脱敏。容器友好（stdout）。"""
from __future__ import annotations

import logging
import re
import sys

import structlog

_SENSITIVE = re.compile(
    r"(api[_-]?key|secret|password|token|authorization|map[_-]?key|ak|sk)\s*[=:]\s*[^\s,;\"']+",
    re.IGNORECASE,
)


def _mask(value: str) -> str:
    return _SENSITIVE.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=***", value) if "=" in value or ":" in value else value


def _scrub(_logger, _name, event_dict: dict) -> dict:
    for key, value in list(event_dict.items()):
        if isinstance(value, str) and any(
            word in key.lower() for word in ("key", "secret", "password", "token", "auth")
        ):
            event_dict[key] = "***"
        elif isinstance(value, str):
            event_dict[key] = _SENSITIVE.sub("***", value)
    return event_dict


_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _scrub,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "flashtrip"):
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
