"""Tests for the per-tool concurrency / timeout guard in ``server.py``."""

from __future__ import annotations

import asyncio

import pytest

from codesearch_mcp.errors import ErrorCode, ToolError
from codesearch_mcp.server import (
    QUEUE_TIMEOUT_SECONDS,
    ToolExecutionGuard,
    _dispatch,
    _to_is_error,
)

pytestmark = pytest.mark.asyncio


async def test_guard_raises_timeout_on_queue_wait() -> None:
    """When the semaphore is saturated and a new call cannot acquire it
    within ``queue_timeout``, the guard raises ``ToolError(TIMEOUT)`` with
    a queue-specific message (lines 94-95)."""
    guard = ToolExecutionGuard(max_concurrent=1)
    held = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> str:
        held.set()
        await release.wait()
        return "done"

    holder_task = asyncio.create_task(guard.run("search_code", holder, per_tool_timeout=10.0))
    await held.wait()
    try:
        with pytest.raises(ToolError) as ei:
            await guard.run(
                "search_code",
                lambda: asyncio.sleep(0),
                per_tool_timeout=10.0,
                queue_timeout=0.05,
            )
        assert ei.value.code is ErrorCode.TIMEOUT
        assert "queue" in ei.value.message
    finally:
        release.set()
        await holder_task


async def test_guard_raises_timeout_when_tool_runs_long() -> None:
    """A tool function that runs longer than ``per_tool_timeout`` causes the
    guard to raise ``ToolError(TIMEOUT)`` with a processing-specific message
    (line 112)."""
    guard = ToolExecutionGuard()

    async def slow() -> str:
        await asyncio.sleep(1.0)
        return "never"

    with pytest.raises(ToolError) as ei:
        await guard.run("search_code", slow, per_tool_timeout=0.05)
    assert ei.value.code is ErrorCode.TIMEOUT
    assert "processing" in ei.value.message


async def test_guard_raises_timeout_when_queue_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the queue wait consumes the whole ``queue_timeout`` budget,
    ``remaining_tool`` falls to ``<= 0`` and the guard raises a total-time
    TIMEOUT immediately (line 104).

    We simulate it by monkeypatching ``time.monotonic`` so the second call
    inside ``run`` observes elapsed > queue_timeout."""
    import codesearch_mcp.server as server_mod

    guard = ToolExecutionGuard()
    # The guard calls ``time.monotonic`` twice (start, then elapsed). Any
    # spurious extra calls (e.g. from logging internals) get the same final
    # value so we never see StopIteration.
    values = iter([100.0])
    final = [200.0]

    def fake_monotonic() -> float:
        try:
            return next(values)
        except StopIteration:
            return final[0]

    monkeypatch.setattr(server_mod.time, "monotonic", fake_monotonic)

    async def runner() -> str:
        return "should not run"

    with pytest.raises(ToolError) as ei:
        await guard.run("search_code", runner, per_tool_timeout=10.0, queue_timeout=5.0)
    assert ei.value.code is ErrorCode.TIMEOUT
    assert "total time" in ei.value.message


async def test_dispatch_wraps_unhandled_exception_as_internal_error() -> None:
    """A non-``ToolError`` exception inside a tool runner is logged via
    ``logger.exception`` and converted into an ``INTERNAL_ERROR`` envelope
    (lines 175-177)."""
    guard = ToolExecutionGuard()

    async def boom() -> str:
        raise RuntimeError("kaboom")

    result = await _dispatch(guard, "search_code", boom)
    # ``_dispatch`` returns an isError CallToolResult on the error path.
    assert result.isError is True
    body = result.content[0].text
    assert "INTERNAL_ERROR" in body


async def test_to_is_error_round_trip() -> None:
    err = ToolError(ErrorCode.INVALID_PATH, "bad", {"path": "/x"})
    result = _to_is_error(err)
    assert result.isError is True
    assert "INVALID_PATH" in result.content[0].text


async def test_attach_output_schemas_skips_unregistered_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """``_attach_output_schemas`` silently skips entries in
    ``TOOL_OUTPUT_MODELS`` that the mcp tool manager does not know about
    (line 137)."""
    import codesearch_mcp.server as server_mod
    from codesearch_mcp.config.models import RepositoryConfig, Settings
    from codesearch_mcp.giturl import Hosting
    from codesearch_mcp.repo.manager import RepositoryManager
    from codesearch_mcp.tool_outputs import TOOL_OUTPUT_MODELS

    extra_models = dict(TOOL_OUTPUT_MODELS)
    # Inject a phantom entry whose name has no matching @mcp.tool registration.
    extra_models["nonexistent_tool"] = next(iter(TOOL_OUTPUT_MODELS.values()))
    monkeypatch.setattr(server_mod, "TOOL_OUTPUT_MODELS", extra_models)

    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="probe",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/probe",
            )
        ],
        workspace_root=str(tmp_path) + "/ws",  # type: ignore[operator]
    )
    # Should not raise even with the phantom entry present.
    server_mod.build_server(settings, RepositoryManager(settings))


# Reference unused symbol to satisfy a strict linter that might otherwise
# flag the test-only import. (Coverage already requires it.)
_ = QUEUE_TIMEOUT_SECONDS
