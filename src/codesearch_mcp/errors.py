"""Error codes and tool error payload serialization (spec §5)."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    REPO_NOT_READY = "REPO_NOT_READY"
    INVALID_PATH = "INVALID_PATH"
    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    INVALID_PATTERN = "INVALID_PATTERN"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_BINARY = "FILE_BINARY"
    TIMEOUT = "TIMEOUT"
    BACKEND_FAILURE = "BACKEND_FAILURE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ToolError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if message.endswith("."):
            raise ValueError("ToolError message must not end with a period")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details) if details else {}


def error_payload(err: ToolError) -> str:
    return json.dumps(
        {"code": err.code.value, "message": err.message, "details": err.details},
        ensure_ascii=False,
        separators=(",", ":"),
    )
