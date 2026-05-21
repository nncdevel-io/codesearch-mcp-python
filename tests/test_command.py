"""Tests for the async command runner."""

from __future__ import annotations

import sys

import pytest

from codesearch_mcp.backends.command import run_checked, run_command
from codesearch_mcp.errors import ErrorCode, ToolError

pytestmark = pytest.mark.asyncio


async def test_run_command_captures_stdout() -> None:
    res = await run_command([sys.executable, "-c", "print('hi')"])
    assert res.returncode == 0
    assert res.stdout.strip() == b"hi"


async def test_run_command_returns_nonzero_without_raising() -> None:
    res = await run_command([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert res.returncode == 3


async def test_run_command_times_out() -> None:
    with pytest.raises(ToolError) as ei:
        await run_command(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout=0.1,
        )
    assert ei.value.code == ErrorCode.TIMEOUT


async def test_run_checked_maps_nonzero_to_backend_failure() -> None:
    with pytest.raises(ToolError) as ei:
        await run_checked(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom\\n'); sys.exit(7)"]
        )
    assert ei.value.code == ErrorCode.BACKEND_FAILURE
    assert ei.value.details["returncode"] == 7
    assert "boom" in ei.value.details["stderr"]
