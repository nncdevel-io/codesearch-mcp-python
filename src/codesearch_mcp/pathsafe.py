"""Relative path validation and workspace-contained path resolution (spec §3.2, §5.2)."""

from __future__ import annotations

import posixpath
from pathlib import Path

from .errors import ErrorCode, ToolError


def normalize_relative(path: str) -> str:
    """Normalize a POSIX relative path. Reject absolute paths, ``..``, and backslash.

    Returns the normalized form (e.g. ``"src//main"`` -> ``"src/main"``,
    ``"./src"`` -> ``"src"``). The empty string represents the root and is allowed.
    """

    if "\\" in path:
        raise ToolError(
            ErrorCode.INVALID_PATH,
            "backslash is not allowed in relative paths",
            {"path": path},
        )
    if path.startswith("/"):
        raise ToolError(
            ErrorCode.INVALID_PATH,
            "absolute paths are not allowed",
            {"path": path},
        )
    if not path or path == ".":
        return ""

    normalized = posixpath.normpath(path)
    if normalized == ".":
        return ""
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        raise ToolError(
            ErrorCode.INVALID_PATH,
            "path traversal is not allowed",
            {"path": path},
        )
    parts = normalized.split("/")
    if any(part == ".." for part in parts):  # pragma: no cover
        # Defensive: any ``..`` part should already have been trapped by the
        # ``startswith("../") or normalized == ".."`` check above, since
        # ``posixpath.normpath`` collapses interior ``..`` and only leaves it
        # when the path begins with one.
        raise ToolError(
            ErrorCode.INVALID_PATH,
            "path traversal is not allowed",
            {"path": path},
        )
    return normalized


def resolve_within_workspace(workspace: Path, rel_path: str) -> Path:
    """Resolve a relative path inside the workspace, following symlinks safely.

    Raises ``INVALID_PATH`` if the resolved target escapes ``workspace`` (e.g. via
    a symlink) or contains traversal. Raises ``PATH_NOT_FOUND`` if the path does
    not exist within the workspace.
    """

    normalized = normalize_relative(rel_path)
    workspace_real = workspace.resolve()
    candidate = workspace_real if normalized == "" else workspace_real / normalized
    if not candidate.exists():
        raise ToolError(
            ErrorCode.PATH_NOT_FOUND,
            "path does not exist within the repository",
            {"path": rel_path},
        )
    resolved = candidate.resolve()
    try:
        resolved.relative_to(workspace_real)
    except ValueError as exc:
        raise ToolError(
            ErrorCode.INVALID_PATH,
            "path escapes the repository workspace",
            {"path": rel_path},
        ) from exc
    return resolved
