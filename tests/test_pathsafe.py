"""Tests for the pathsafe module."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesearch_mcp.errors import ErrorCode, ToolError
from codesearch_mcp.pathsafe import normalize_relative, resolve_within_workspace


@pytest.mark.parametrize("path", ["", "src", "src/main", "src/main/file.py", "a/b/c"])
def test_normalize_accepts_valid_relative_paths(path: str) -> None:
    assert normalize_relative(path) == path


@pytest.mark.parametrize(
    "path",
    ["/abs", "/etc/passwd", "../escape", "src/../../escape", "./..", "..", "a/../.."],
)
def test_normalize_rejects_absolute_and_parent_paths(path: str) -> None:
    with pytest.raises(ToolError) as ei:
        normalize_relative(path)
    assert ei.value.code == ErrorCode.INVALID_PATH


def test_normalize_strips_redundant_components() -> None:
    assert normalize_relative("./src") == "src"
    assert normalize_relative("src//main") == "src/main"
    assert normalize_relative("src/./main") == "src/main"


def test_normalize_rejects_backslash_separator() -> None:
    with pytest.raises(ToolError) as ei:
        normalize_relative("src\\main")
    assert ei.value.code == ErrorCode.INVALID_PATH


def test_resolve_within_workspace_returns_realpath(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    target = ws / "src" / "file.py"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    resolved = resolve_within_workspace(ws, "src/file.py")
    assert resolved == target.resolve()


def test_resolve_within_workspace_root_when_empty(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    assert resolve_within_workspace(ws, "") == ws.resolve()


def test_resolve_within_workspace_missing_path_raises_path_not_found(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(ToolError) as ei:
        resolve_within_workspace(ws, "src/missing.py")
    assert ei.value.code == ErrorCode.PATH_NOT_FOUND


def test_resolve_within_workspace_symlink_escape_raises_invalid_path(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "escape").symlink_to(outside)
    with pytest.raises(ToolError) as ei:
        resolve_within_workspace(ws, "escape")
    assert ei.value.code == ErrorCode.INVALID_PATH


def test_resolve_within_workspace_rejects_absolute_input(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(ToolError) as ei:
        resolve_within_workspace(ws, "/etc/passwd")
    assert ei.value.code == ErrorCode.INVALID_PATH
