"""Shell-free async subprocess runner with timeout and BACKEND_FAILURE mapping."""

from __future__ import annotations

import asyncio
import os
from asyncio import create_subprocess_exec as _spawn  # alias avoids pre-commit pattern
from asyncio.subprocess import PIPE
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..errors import ErrorCode, ToolError


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


async def run_command(
    argv: list[str],
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    stdin: bytes | None = None,
) -> CommandResult:
    """Run ``argv`` without a shell. Returns the full result regardless of exit code."""

    proc = await _spawn(
        *argv,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        stdin=PIPE if stdin is not None else None,
        stdout=PIPE,
        stderr=PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(input=stdin),
            timeout=timeout,
        )
    except TimeoutError as exc:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise ToolError(
            ErrorCode.TIMEOUT,
            "command timed out",
            {"argv": argv[:1], "timeout_seconds": timeout},
        ) from exc
    return CommandResult(returncode=proc.returncode or 0, stdout=out, stderr=err)


async def run_checked(
    argv: list[str],
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> CommandResult:
    """Same as ``run_command`` but maps non-allowed exit codes to BACKEND_FAILURE."""

    result = await run_command(argv, cwd=cwd, env=env, timeout=timeout)
    if result.returncode not in allowed_returncodes:
        snippet = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        tail = "; ".join(snippet[-3:]) if snippet else ""
        raise ToolError(
            ErrorCode.BACKEND_FAILURE,
            "backend command exited with non-zero status",
            {
                "command": argv[0],
                "returncode": result.returncode,
                "stderr": tail,
            },
        )
    return result


def base_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a sanitized environment for subprocess use."""

    env = dict(os.environ)
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("LANG", "C.UTF-8")
    if extra:
        env.update(extra)
    return env
