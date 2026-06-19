"""Tests for DEBUG-level JSON-RPC message logging (TASK-079..081)."""

from __future__ import annotations

import io
import json
import logging as stdlib_logging
from pathlib import Path

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.logging import JsonFormatter, get_logger
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.server import (
    _log_jsonrpc,
    _LoggingReceiveStream,
    _LoggingSendStream,
    build_server,
)


def _capture(logger: stdlib_logging.Logger) -> tuple[io.StringIO, stdlib_logging.Handler]:
    buf = io.StringIO()
    handler = stdlib_logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return buf, handler


def _request(method: str = "ping", params: dict | None = None) -> SessionMessage:
    req = JSONRPCRequest(jsonrpc="2.0", id=1, method=method, params=params)
    return SessionMessage(message=JSONRPCMessage(req))


def _events(buf: io.StringIO) -> list[dict]:
    lines = [ln for ln in buf.getvalue().strip().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_log_jsonrpc_emits_full_message_at_debug() -> None:
    logger = get_logger()
    prev = logger.level
    logger.setLevel(stdlib_logging.DEBUG)
    buf, handler = _capture(logger)
    try:
        _log_jsonrpc("incoming", _request("tools/call"))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    evt = [e for e in _events(buf) if e["ctx"]["event"] == "jsonrpc_message"]
    assert evt, "expected a jsonrpc_message event"
    assert evt[0]["ctx"]["direction"] == "incoming"
    assert evt[0]["ctx"]["message"]["method"] == "tools/call"


def test_log_jsonrpc_suppressed_below_debug() -> None:
    logger = get_logger()
    prev = logger.level
    logger.setLevel(stdlib_logging.INFO)
    buf, handler = _capture(logger)
    try:
        _log_jsonrpc("incoming", _request())
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    assert "jsonrpc_message" not in buf.getvalue()


def test_log_jsonrpc_handles_exception_item() -> None:
    logger = get_logger()
    prev = logger.level
    logger.setLevel(stdlib_logging.DEBUG)
    buf, handler = _capture(logger)
    try:
        _log_jsonrpc("incoming", ValueError("boom"))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    evt = [e for e in _events(buf) if e["ctx"]["event"] == "jsonrpc_message"]
    assert "boom" in evt[0]["ctx"]["error"]


def test_log_jsonrpc_redacts_secrets() -> None:
    logger = get_logger()
    prev = logger.level
    logger.setLevel(stdlib_logging.DEBUG)
    buf, handler = _capture(logger)
    try:
        msg = _request(
            "tools/call",
            {"name": "search_code", "arguments": {"pattern": "token=abc123"}},
        )
        _log_jsonrpc("incoming", msg)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    body = buf.getvalue()
    assert "abc123" not in body
    assert "token=***" in body


async def test_receive_stream_logs_and_passes_through() -> None:
    logger = get_logger()
    prev = logger.level
    logger.setLevel(stdlib_logging.DEBUG)
    buf, handler = _capture(logger)
    send, recv = anyio.create_memory_object_stream(8)
    wrapped = _LoggingReceiveStream(recv, "incoming")
    msg = _request("ping")
    try:
        async with send:
            await send.send(msg)
        received: list[object] = []
        async with wrapped:
            async for item in wrapped:
                received.append(item)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    assert received == [msg]
    evt = [e for e in _events(buf) if e["ctx"]["event"] == "jsonrpc_message"]
    assert evt and evt[0]["ctx"]["direction"] == "incoming"


async def test_send_stream_logs_and_forwards() -> None:
    logger = get_logger()
    prev = logger.level
    logger.setLevel(stdlib_logging.DEBUG)
    buf, handler = _capture(logger)
    send, recv = anyio.create_memory_object_stream(8)
    wrapped = _LoggingSendStream(send, "outgoing")
    msg = _request("pong")
    try:
        async with wrapped:
            await wrapped.send(msg)
        got: list[object] = []
        async with recv:
            async for item in recv:
                got.append(item)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    assert got == [msg]
    evt = [e for e in _events(buf) if e["ctx"]["event"] == "jsonrpc_message"]
    assert evt and evt[0]["ctx"]["direction"] == "outgoing"


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


async def test_jsonrpc_logged_both_directions_at_debug(tmp_path: Path) -> None:
    settings, mgr = _minimal(tmp_path)
    server = build_server(settings, mgr)
    logger = get_logger()
    prev = logger.level
    logger.setLevel(stdlib_logging.DEBUG)
    buf, handler = _capture(logger)
    try:
        async with create_connected_server_and_client_session(server) as client:
            await client.initialize()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    jl = [e for e in _events(buf) if e.get("ctx", {}).get("event") == "jsonrpc_message"]
    directions = {e["ctx"]["direction"] for e in jl}
    assert "incoming" in directions
    assert "outgoing" in directions


async def test_jsonrpc_not_logged_at_info(tmp_path: Path) -> None:
    settings, mgr = _minimal(tmp_path)
    server = build_server(settings, mgr)
    logger = get_logger()
    prev = logger.level
    logger.setLevel(stdlib_logging.INFO)
    buf, handler = _capture(logger)
    try:
        async with create_connected_server_and_client_session(server) as client:
            await client.initialize()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    assert "jsonrpc_message" not in buf.getvalue()
