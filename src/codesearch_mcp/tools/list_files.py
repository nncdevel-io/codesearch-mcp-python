"""list_files tool implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..backends.command import base_env, run_command
from ..backends.ripgrep import build_files_argv
from ..config.models import RepositoryConfig
from ..errors import ErrorCode, ToolError
from ..giturl import build_url
from ..pathsafe import normalize_relative
from ..repo.manager import RepositoryManager
from .schemas import ListFilesInput

_LIST_FILES_TIMEOUT_SECONDS = 4.5


def _git_url(repo: RepositoryConfig, path: str) -> str:
    return build_url(
        repo.hosting,
        base_url=repo.hosting_base_url,
        branch=repo.branch,
        path=path,
        start_line=1,
    )


def _excluded(path: str, exclude_prefixes: tuple[str, ...]) -> bool:
    for prefix in exclude_prefixes:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return True
    return False


async def execute_list_files(manager: RepositoryManager, payload: ListFilesInput) -> dict[str, Any]:
    workspace = manager.require_ready(payload.repository)
    repo_cfg = manager.config(payload.repository)
    subpath = normalize_relative(payload.path) if payload.path else None

    argv = build_files_argv(pattern=payload.pattern, path=subpath)
    res = await run_command(
        argv,
        cwd=workspace,
        env=base_env(),
        timeout=_LIST_FILES_TIMEOUT_SECONDS,
    )
    if res.returncode == 2:
        stderr = res.stderr.decode("utf-8", errors="replace").strip()
        if "glob" in stderr.lower() and "error" in stderr.lower():
            raise ToolError(
                ErrorCode.INVALID_PATTERN,
                "glob pattern is invalid",
                {"stderr": stderr.splitlines()[-1] if stderr else ""},
            )
        raise ToolError(
            ErrorCode.BACKEND_FAILURE,
            "ripgrep --files exited with error",
            {"stderr": stderr.splitlines()[-1] if stderr else ""},
        )
    raw_paths = res.stdout.decode("utf-8", errors="replace").splitlines()
    normalized = [p[2:] if p.startswith("./") else p for p in raw_paths if p]
    paths = [p for p in normalized if not _excluded(p, tuple(repo_cfg.exclude_paths))]

    enriched: list[tuple[str, datetime]] = []
    for rel in paths:
        target = workspace / rel
        try:
            mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC)
        except FileNotFoundError:
            continue
        enriched.append((rel, mtime))
    enriched.sort(key=lambda t: (-t[1].timestamp(), t[0]))
    truncated = len(enriched) > payload.max_results
    enriched = enriched[: payload.max_results]

    return {
        "files": [
            {
                "repository": payload.repository,
                "file_path": rel,
                "last_modified": mtime.isoformat().replace("+00:00", "Z"),
                "git_url": _git_url(repo_cfg, rel),
            }
            for rel, mtime in enriched
        ],
        "truncated": truncated,
    }
