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


def test_redact_recurses_into_lists() -> None:
    """``_redact_value`` recurses into list elements (line 41).

    Reach it via a context whose value is a list containing a credentialed URL."""
    record = stdlib_logging.LogRecord(
        name="t",
        level=stdlib_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="x",
        args=(),
        exc_info=None,
    )
    record.ctx = {  # type: ignore[attr-defined]
        "remotes": ["https://x-access-token:abc@host/r.git", "plain"],
    }
    parsed = json.loads(JsonFormatter().format(record))
    assert parsed["ctx"]["remotes"][0].endswith("@host/r.git")
    assert "abc" not in parsed["ctx"]["remotes"][0]
    assert "***" in parsed["ctx"]["remotes"][0]
    assert parsed["ctx"]["remotes"][1] == "plain"


def _record_with_exc() -> stdlib_logging.LogRecord:
    try:
        raise RuntimeError("boom https://x-access-token:abc@h/r")
    except RuntimeError:
        import sys

        return stdlib_logging.LogRecord(
            name="t",
            level=stdlib_logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )


def test_json_formatter_includes_redacted_exception() -> None:
    """``JsonFormatter`` attaches an ``exc`` field built from the formatted
    traceback, with secrets redacted (line 59)."""
    parsed = json.loads(JsonFormatter().format(_record_with_exc()))
    assert "exc" in parsed
    assert "abc" not in parsed["exc"]
    assert "***" in parsed["exc"]


def test_text_formatter_appends_redacted_exception() -> None:
    """``TextFormatter`` appends the formatted exception, also redacted
    (line 82)."""
    line = TextFormatter().format(_record_with_exc())
    assert "abc" not in line
    assert "***" in line
    assert "Traceback" in line


def test_format_value_quotes_string_with_space_or_equals() -> None:
    """``_format_value`` JSON-encodes strings containing ``" "`` or ``"="`` so
    the ``k=v`` rendering remains unambiguous (line 89)."""
    record = stdlib_logging.LogRecord(
        name="t",
        level=stdlib_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="m",
        args=(),
        exc_info=None,
    )
    record.ctx = {"note": "has space", "raw": "k=v"}  # type: ignore[attr-defined]
    line = TextFormatter().format(record)
    # JSON-quoted because of the space / '=' inside.
    assert 'note="has space"' in line
    assert 'raw="k=v"' in line


def test_format_value_json_encodes_dict_and_list_values() -> None:
    """``_format_value`` compact-JSON-encodes dict/list values (line 91)."""
    record = stdlib_logging.LogRecord(
        name="t",
        level=stdlib_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="m",
        args=(),
        exc_info=None,
    )
    record.ctx = {"d": {"a": 1}, "lst": [1, 2]}  # type: ignore[attr-defined]
    line = TextFormatter().format(record)
    assert 'd={"a":1}' in line
    assert "lst=[1,2]" in line


def test_text_formatter_with_only_event_in_ctx_omits_trailing_kv() -> None:
    """When ``ctx`` contains *only* the reserved ``event`` key, no ``kv`` tail
    is appended (branch 79→81: kv is empty after filtering)."""
    record = stdlib_logging.LogRecord(
        name="t",
        level=stdlib_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="m",
        args=(),
        exc_info=None,
    )
    record.ctx = {"event": "ping"}  # type: ignore[attr-defined]
    line = TextFormatter().format(record)
    # Just the header — no ``  k=v`` suffix.
    assert line.endswith(" m")


def test_text_formatter_without_ctx_skips_kv_block() -> None:
    """No ``ctx`` extra → the dict branch in TextFormatter is bypassed (branch
    76→81)."""
    record = stdlib_logging.LogRecord(
        name="t",
        level=stdlib_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="m",
        args=(),
        exc_info=None,
    )
    # No ctx attribute set.
    line = TextFormatter().format(record)
    assert line.endswith(" m")
