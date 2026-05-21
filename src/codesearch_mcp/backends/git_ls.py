"""Wrapper around git ls-files for tracked-file enumeration."""

from __future__ import annotations

from pathlib import Path

from .command import base_env, run_checked


async def list_tracked_files(
    workspace: Path, *, subpath: str | None = None, timeout: float = 30.0
) -> list[str]:
    argv = ["git", "ls-files", "-z"]
    if subpath:
        argv += ["--", subpath]
    res = await run_checked(argv, cwd=workspace, env=base_env(), timeout=timeout)
    raw = res.stdout
    if not raw:
        return []
    parts = raw.split(b"\x00")
    return [p.decode("utf-8", errors="replace") for p in parts if p]
