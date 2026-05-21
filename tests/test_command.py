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


async def test_run_command_swallows_process_lookup_on_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``proc.kill()`` races against natural exit and raises
    ``ProcessLookupError``, the runner still reports TIMEOUT cleanly
    (lines 49-50)."""

    class _Proc:
        returncode: int | None = None

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            raise TimeoutError

        def kill(self) -> None:
            raise ProcessLookupError("already gone")

        async def wait(self) -> int:
            self.returncode = -9
            return -9

    async def _fake_spawn(*args: object, **kwargs: object) -> _Proc:
        return _Proc()

    import codesearch_mcp.backends.command as cmd

    monkeypatch.setattr(cmd, "_spawn", _fake_spawn)
    with pytest.raises(ToolError) as ei:
        await cmd.run_command(["whatever"], timeout=0.1)
    assert ei.value.code == ErrorCode.TIMEOUT


async def test_base_env_sets_locale_and_merges_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codesearch_mcp.backends.command import base_env

    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    env = base_env({"FOO": "bar"})
    assert env["LC_ALL"] == "C.UTF-8"
    assert env["LANG"] == "C.UTF-8"
    assert env["FOO"] == "bar"
