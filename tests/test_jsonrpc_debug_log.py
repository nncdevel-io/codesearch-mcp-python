"""Tests for DEBUG-level JSON-RPC message logging (design §8)."""

from __future__ import annotations

import io
import json
import logging as stdlib_logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from mcp import Client, MCPError, types

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.logging import JsonFormatter, get_logger
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.server import _dump_result, _log_jsonrpc, build_server


@contextmanager
def _captured_log(level: int) -> Iterator[io.StringIO]:
    logger = get_logger()
    prev = logger.level
    logger.setLevel(level)
    buf = io.StringIO()
    handler = stdlib_logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    try:
        yield buf
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)


def _jsonrpc_events(buf: io.StringIO) -> list[dict]:
    lines = [ln for ln in buf.getvalue().strip().splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    return [e["ctx"] for e in events if e.get("ctx", {}).get("event") == "jsonrpc_message"]


def test_log_jsonrpc_redacts_secrets() -> None:
    with _captured_log(stdlib_logging.DEBUG) as buf:
        _log_jsonrpc(
            "incoming",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search_code", "arguments": {"pattern": "token=abc123"}},
            },
        )
    body = buf.getvalue()
    assert "abc123" not in body
    assert "token=***" in body


def test_dump_result_maps_dict_and_none_to_wire_result() -> None:
    assert _dump_result({"tools": []}) == {"tools": []}
    assert _dump_result(None) == {}


def test_dump_result_serializes_model_with_wire_aliases() -> None:
    result = types.CallToolResult(is_error=True, content=[])
    dumped = _dump_result(result)
    assert dumped["isError"] is True
    assert "is_error" not in dumped


def _minimal(tmp_path: Path) -> tuple[Settings, RepositoryManager]:
    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="alpha",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/alpha",
            )
        ],
        workspace_root=str(tmp_path / "ws"),
    )
    return settings, RepositoryManager(settings)


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_request_and_response_logged_at_debug(tmp_path: Path, mode: str) -> None:
    settings, mgr = _minimal(tmp_path)
    server = build_server(settings, mgr)
    with _captured_log(stdlib_logging.DEBUG) as buf:
        async with Client(server, mode=mode) as client:
            await client.list_tools()
    events = _jsonrpc_events(buf)
    incoming = [e["message"] for e in events if e["direction"] == "incoming"]
    outgoing = [e["message"] for e in events if e["direction"] == "outgoing"]
    request = next(m for m in incoming if m["method"] == "tools/list")
    response = next(m for m in outgoing if m["id"] == request["id"])
    assert {t["name"] for t in response["result"]["tools"]} >= {"search_code", "read_file"}


async def test_notification_logged_without_response(tmp_path: Path) -> None:
    settings, mgr = _minimal(tmp_path)
    server = build_server(settings, mgr)
    with _captured_log(stdlib_logging.DEBUG) as buf:
        async with Client(server, mode="legacy"):
            pass
    events = _jsonrpc_events(buf)
    notification = next(
        e["message"] for e in events if e["message"].get("method") == "notifications/initialized"
    )
    assert "id" not in notification
    assert all("id" in e["message"] for e in events if e["direction"] == "outgoing")


async def test_failed_request_logs_error_response(tmp_path: Path) -> None:
    settings, mgr = _minimal(tmp_path)
    server = build_server(settings, mgr)
    with _captured_log(stdlib_logging.DEBUG) as buf:
        async with Client(server, mode="legacy") as client:
            with pytest.raises(MCPError):
                await client.read_resource("codesearch://repo/does-not-exist")
    outgoing = [e["message"] for e in _jsonrpc_events(buf) if e["direction"] == "outgoing"]
    assert any("Unknown resource" in m.get("error", "") for m in outgoing)


async def test_jsonrpc_not_logged_at_info(tmp_path: Path) -> None:
    settings, mgr = _minimal(tmp_path)
    server = build_server(settings, mgr)
    with _captured_log(stdlib_logging.INFO) as buf:
        async with Client(server, mode="legacy") as client:
            await client.list_tools()
    assert "jsonrpc_message" not in buf.getvalue()
