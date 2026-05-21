"""Tests for the observability report and structured logging helpers."""

from __future__ import annotations

import io
import json
import logging as stdlib_logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.logging import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    get_logger,
    log_event,
    redact,
)
from codesearch_mcp.observability import sync_status_report
from codesearch_mcp.repo.manager import RepositoryManager, RepositoryState, SyncOutcome


def _build_manager(tmp_path: Path) -> RepositoryManager:
    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="alpha",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/alpha",
            ),
            RepositoryConfig(
                id="beta",
                remote="y",
                branch="main",
                hosting=Hosting.GITLAB,
                hosting_base_url="https://gitlab.com/o/beta",
            ),
        ],
        workspace_root=str(tmp_path / "ws"),
    )
    return RepositoryManager(settings)


def test_sync_status_report_shape(tmp_path: Path) -> None:
    mgr = _build_manager(tmp_path)
    mgr.mark_success("alpha", "deadbeef")
    mgr.mark_failure("beta", "fetch failed")
    report = sync_status_report(mgr)
    assert {entry["repository"] for entry in report} == {"alpha", "beta"}
    alpha = next(e for e in report if e["repository"] == "alpha")
    beta = next(e for e in report if e["repository"] == "beta")
    assert alpha["state"] == RepositoryState.READY.value
    assert alpha["last_outcome"] == SyncOutcome.SUCCESS.value
    assert alpha["last_commit"] == "deadbeef"
    assert alpha["last_error"] is None
    assert alpha["last_sync_at"].endswith("Z")
    assert beta["last_outcome"] == SyncOutcome.FAILURE.value
    assert beta["last_error"] == "fetch failed"


def test_sync_status_report_uninitialized(tmp_path: Path) -> None:
    mgr = _build_manager(tmp_path)
    report = sync_status_report(mgr)
    for entry in report:
        assert entry["state"] == RepositoryState.UNINITIALIZED.value
        assert entry["last_outcome"] is None
        assert entry["last_sync_at"] is None


def test_redact_url_credentials() -> None:
    assert (
        redact("https://x-access-token:ghp_secret@github.com/o/r.git")
        == "https://x-access-token:***@github.com/o/r.git"
    )
    assert redact("token=abcdef1234") == "token=***"
    assert (
        redact("Authorization=Bearer xyz123") == "Authorization=***"
        or redact("Authorization=Bearer xyz123") == "authorization=***"
        or "***" in redact("Authorization=Bearer xyz123")
    )


def test_json_formatter_emits_json_with_ctx_and_redaction() -> None:
    record = stdlib_logging.LogRecord(
        name="test",
        level=stdlib_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="cloned %s",
        args=("https://x-access-token:abc@github.com/o/r.git",),
        exc_info=None,
    )
    record.ctx = {  # type: ignore[attr-defined]
        "remote": "https://x-access-token:abc@github.com/o/r.git",
        "ok": True,
    }
    formatted = JsonFormatter().format(record)
    parsed = json.loads(formatted)
    assert parsed["level"] == "INFO"
    assert "***" in parsed["msg"]
    assert "***" in parsed["ctx"]["remote"]
    assert parsed["ctx"]["ok"] is True


def test_log_event_writes_to_configured_logger() -> None:
    configure_logging()
    logger = get_logger()
    # Capture by attaching a memory handler temporarily.
    buf = io.StringIO()
    handler = stdlib_logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    try:
        log_event("info", "test_event", repository="alpha")
    finally:
        logger.removeHandler(handler)
    line = buf.getvalue().strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["ctx"]["event"] == "test_event"
    assert parsed["ctx"]["repository"] == "alpha"


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    handlers_before = len(get_logger().handlers)
    configure_logging()
    assert len(get_logger().handlers) == handlers_before


def test_json_formatter_records_timestamp_in_utc() -> None:
    record = stdlib_logging.LogRecord(
        name="t",
        level=stdlib_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="x",
        args=(),
        exc_info=None,
    )
    parsed = json.loads(JsonFormatter().format(record))
    # Should parse as a real ISO timestamp ending in Z (UTC).
    ts = parsed["ts"]
    assert ts.endswith("Z")
    datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def test_text_formatter_is_human_readable_and_redacts() -> None:
    record = stdlib_logging.LogRecord(
        name="t",
        level=stdlib_logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="server_start",
        args=(),
        exc_info=None,
    )
    record.ctx = {  # type: ignore[attr-defined]
        "event": "server_start",
        "remote": "https://x-access-token:abc@github.com/o/r.git",
        "ok": True,
    }
    line = TextFormatter().format(record)
    # No JSON braces around the whole record; flat human form.
    assert not line.startswith("{")
    assert "WARNING" in line
    assert "server_start" in line
    # Secrets are redacted in the text rendering too.
    assert "abc" not in line
    assert "***" in line
    # The reserved "event" key is not duplicated as a kv pair.
    assert "event=server_start" not in line


def test_configure_logging_picks_text_on_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    # Reset any pre-existing handlers so configure_logging actually wires one.
    logger = get_logger()
    logger.handlers.clear()
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    configure_logging()
    handler = logger.handlers[0]
    assert isinstance(handler.formatter, TextFormatter)
    logger.handlers.clear()


def test_configure_logging_picks_json_when_not_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    logger = get_logger()
    logger.handlers.clear()
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    configure_logging()
    handler = logger.handlers[0]
    assert isinstance(handler.formatter, JsonFormatter)
    logger.handlers.clear()
