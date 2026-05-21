"""Structured logging with secret redaction (TASK-027)."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

_LOGGER_NAME = "codesearch_mcp"

# Patterns that commonly carry secrets in URLs / env values.
# Order matters: more specific (x-access-token) is tried before the generic
# user:pass and the user:pass pattern uses a negative look-ahead so it does
# not re-rewrite the already-redacted form.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(https?://)x-access-token:[^@\s]+@"), r"\1x-access-token:***@"),
    (
        re.compile(r"(https?://)(?!x-access-token:|\*\*\*:)[^/@\s:]+:[^@\s]+@"),
        r"\1***:***@",
    ),
    (re.compile(r"(token=)[A-Za-z0-9_\-\.]+"), r"\1***"),
    (re.compile(r"(authorization=)[^&\s]+", re.IGNORECASE), r"\1***"),
]


def redact(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "ctx", None)
        if isinstance(extra, dict):
            payload["ctx"] = _redact_value(extra)
        if record.exc_info:
            # Spec §5.3: no stack traces in *error responses*; logs may include them
            # but redact secrets just in case.
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def configure_logging(level: str | int | None = None) -> None:
    logger = get_logger()
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    resolved = level or os.environ.get("CODE_SEARCH_LOG_LEVEL", "INFO")
    logger.setLevel(resolved if isinstance(resolved, int) else resolved.upper())
    logger.propagate = False


def log_event(level: str, event: str, **ctx: Any) -> None:
    logger = get_logger()
    payload = {"event": event, **ctx}
    logger.log(
        getattr(logging, level.upper()),
        event,
        extra={"ctx": payload},
    )
