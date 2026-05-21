"""Tests for ErrorCode and ToolError serialization."""

from __future__ import annotations

import json

import pytest

from codesearch_mcp.errors import ErrorCode, ToolError, error_payload


def test_error_code_values_match_spec() -> None:
    assert ErrorCode.REPO_NOT_FOUND.value == "REPO_NOT_FOUND"
    assert ErrorCode.REPO_NOT_READY.value == "REPO_NOT_READY"
    assert ErrorCode.INVALID_PATH.value == "INVALID_PATH"
    assert ErrorCode.PATH_NOT_FOUND.value == "PATH_NOT_FOUND"
    assert ErrorCode.INVALID_PATTERN.value == "INVALID_PATTERN"
    assert ErrorCode.FILE_TOO_LARGE.value == "FILE_TOO_LARGE"
    assert ErrorCode.FILE_BINARY.value == "FILE_BINARY"
    assert ErrorCode.TIMEOUT.value == "TIMEOUT"
    assert ErrorCode.BACKEND_FAILURE.value == "BACKEND_FAILURE"
    assert ErrorCode.INTERNAL_ERROR.value == "INTERNAL_ERROR"


def test_tool_error_carries_code_message_details() -> None:
    err = ToolError(
        ErrorCode.REPO_NOT_FOUND,
        "Repository 'foo' is not configured",
        {"repository": "foo"},
    )
    assert err.code == ErrorCode.REPO_NOT_FOUND
    assert err.message == "Repository 'foo' is not configured"
    assert err.details == {"repository": "foo"}


def test_tool_error_message_has_no_trailing_period() -> None:
    with pytest.raises(ValueError):
        ToolError(ErrorCode.INVALID_PATH, "absolute paths are forbidden.")


def test_error_payload_serializes_to_json_string() -> None:
    err = ToolError(
        ErrorCode.INVALID_PATH,
        "absolute paths are forbidden",
        {"path": "/etc/passwd"},
    )
    payload = error_payload(err)
    parsed = json.loads(payload)
    assert parsed == {
        "code": "INVALID_PATH",
        "message": "absolute paths are forbidden",
        "details": {"path": "/etc/passwd"},
    }


def test_error_payload_defaults_details_to_empty_object() -> None:
    err = ToolError(ErrorCode.INTERNAL_ERROR, "something failed")
    parsed = json.loads(error_payload(err))
    assert parsed["details"] == {}


def test_tool_error_is_subclass_of_exception() -> None:
    err = ToolError(ErrorCode.INTERNAL_ERROR, "boom")
    assert isinstance(err, Exception)
