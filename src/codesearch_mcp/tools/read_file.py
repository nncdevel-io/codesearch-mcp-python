"""read_file tool implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.models import RepositoryConfig
from ..errors import ErrorCode, ToolError
from ..giturl import build_url
from ..pathsafe import resolve_within_workspace
from ..repo.manager import RepositoryManager
from .schemas import ReadFileInput

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB per spec §4.4.4
_BINARY_PROBE = 8192


def _is_binary(blob: bytes) -> bool:
    if b"\x00" in blob:
        return True
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def format_numbered(lines: list[str], start_line: int, end_line: int) -> str:
    """Render lines with right-aligned line numbers + tab + content (spec §4.4.3)."""

    width = len(str(end_line))
    return "".join(f"{(start_line + idx):>{width}}\t{line}\n" for idx, line in enumerate(lines))


def _build_git_url(repo: RepositoryConfig, file_path: str, start_line: int, end_line: int) -> str:
    return build_url(
        repo.hosting,
        base_url=repo.hosting_base_url,
        branch=repo.branch,
        path=file_path,
        start_line=start_line,
        end_line=end_line,
    )


async def execute_read_file(manager: RepositoryManager, payload: ReadFileInput) -> dict[str, Any]:
    workspace = manager.require_ready(payload.repository)
    repo_cfg = manager.config(payload.repository)
    target = resolve_within_workspace(workspace, payload.file_path)
    if target.is_dir():
        raise ToolError(
            ErrorCode.PATH_NOT_FOUND,
            "target is a directory, not a file",
            {"path": payload.file_path},
        )
    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ToolError(
            ErrorCode.FILE_TOO_LARGE,
            "file exceeds the 10 MiB size limit",
            {"path": payload.file_path, "size_bytes": size, "limit_bytes": MAX_FILE_BYTES},
        )
    blob = target.read_bytes()
    if _is_binary(blob[:_BINARY_PROBE]) or _is_binary(blob):
        raise ToolError(
            ErrorCode.FILE_BINARY,
            "file is not valid UTF-8 text",
            {"path": payload.file_path},
        )
    text = blob.decode("utf-8")
    all_lines = text.splitlines()
    total_lines = len(all_lines)
    start = payload.start_line
    end = min(total_lines, start + payload.num_lines - 1)
    if total_lines == 0:
        selected: list[str] = []
        start_out = 1
        end_out = 0
    elif start > total_lines:
        selected = []
        start_out = total_lines + 1
        end_out = total_lines
    else:
        selected = all_lines[start - 1 : end]
        start_out = start
        end_out = end
    content = format_numbered(selected, start_out, max(end_out, start_out))
    git_url = _build_git_url(
        repo_cfg,
        _relative_posix(workspace, target),
        start_out,
        max(end_out, start_out),
    )
    return {
        "repository": payload.repository,
        "file_path": _relative_posix(workspace, target),
        "start_line": start_out,
        "end_line": end_out,
        "total_lines": total_lines,
        "content": content,
        "git_url": git_url,
    }


def _relative_posix(workspace: Path, target: Path) -> str:
    return target.relative_to(workspace).as_posix()
