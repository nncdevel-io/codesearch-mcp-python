"""Tests for the read_file tool implementation."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.errors import ErrorCode, ToolError
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.tools.read_file import execute_read_file, format_numbered
from codesearch_mcp.tools.schemas import ReadFileInput


def _ctx(tmp_path: Path) -> tuple[RepositoryManager, Path]:
    workspace = tmp_path / "ws" / "alpha"
    workspace.mkdir(parents=True)
    (workspace / ".git").mkdir()  # mark ready
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
    return RepositoryManager(settings), workspace


def test_format_numbered_right_aligns_to_end_line() -> None:
    out = format_numbered(["a", "b", "c"], 9, 11)
    assert out == " 9\ta\n10\tb\n11\tc\n"


async def test_read_file_returns_numbered_content(tmp_path: Path) -> None:
    mgr, ws = _ctx(tmp_path)
    (ws / "src").mkdir()
    (ws / "src" / "a.py").write_text("one\ntwo\nthree\nfour\n")
    res = await execute_read_file(
        mgr, ReadFileInput(repository="alpha", file_path="src/a.py", start_line=2, num_lines=2)
    )
    assert res["start_line"] == 2
    assert res["end_line"] == 3
    assert res["total_lines"] == 4
    assert res["content"] == "2\ttwo\n3\tthree\n"
    assert res["git_url"].endswith("src/a.py#L2-L3")


async def test_read_file_rejects_binary(tmp_path: Path) -> None:
    mgr, ws = _ctx(tmp_path)
    (ws / "bin.dat").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02")
    with pytest.raises(ToolError) as ei:
        await execute_read_file(mgr, ReadFileInput(repository="alpha", file_path="bin.dat"))
    assert ei.value.code == ErrorCode.FILE_BINARY


async def test_read_file_too_large(tmp_path: Path, monkeypatch) -> None:
    mgr, ws = _ctx(tmp_path)
    from codesearch_mcp.tools import read_file as mod

    monkeypatch.setattr(mod, "MAX_FILE_BYTES", 8)
    (ws / "big.txt").write_text("12345678901234")
    with pytest.raises(ToolError) as ei:
        await execute_read_file(mgr, ReadFileInput(repository="alpha", file_path="big.txt"))
    assert ei.value.code == ErrorCode.FILE_TOO_LARGE


async def test_read_file_invalid_path(tmp_path: Path) -> None:
    mgr, _ = _ctx(tmp_path)
    with pytest.raises(ToolError) as ei:
        await execute_read_file(mgr, ReadFileInput(repository="alpha", file_path="../escape"))
    assert ei.value.code == ErrorCode.INVALID_PATH


async def test_read_file_rejects_invalid_utf8(tmp_path: Path) -> None:
    """A file with valid bytes but invalid UTF-8 sequences is detected as
    binary via the ``UnicodeDecodeError`` branch (lines 23-25)."""
    mgr, ws = _ctx(tmp_path)
    # Bytes 0x80-0xBF on their own are invalid UTF-8 continuation bytes.
    (ws / "latin1.txt").write_bytes(b"caf\xe9 latte\n")
    with pytest.raises(ToolError) as ei:
        await execute_read_file(mgr, ReadFileInput(repository="alpha", file_path="latin1.txt"))
    assert ei.value.code == ErrorCode.FILE_BINARY


async def test_read_file_rejects_directory_target(tmp_path: Path) -> None:
    """Pointing ``file_path`` at a directory raises ``PATH_NOT_FOUND`` (line 52)."""
    mgr, ws = _ctx(tmp_path)
    (ws / "src").mkdir()
    with pytest.raises(ToolError) as ei:
        await execute_read_file(mgr, ReadFileInput(repository="alpha", file_path="src"))
    assert ei.value.code is ErrorCode.PATH_NOT_FOUND


async def test_read_file_handles_empty_file(tmp_path: Path) -> None:
    """An empty file → ``total_lines == 0`` branch yielding an empty content
    block and ``end_line == 0`` (lines 76-79)."""
    mgr, ws = _ctx(tmp_path)
    (ws / "empty.txt").write_text("")
    res = await execute_read_file(mgr, ReadFileInput(repository="alpha", file_path="empty.txt"))
    assert res["total_lines"] == 0
    assert res["start_line"] == 1
    assert res["end_line"] == 0
    assert res["content"] == ""


async def test_read_file_start_beyond_eof(tmp_path: Path) -> None:
    """``start_line`` past the end of the file → empty selection and
    ``start_line == total_lines + 1`` (lines 81-83)."""
    mgr, ws = _ctx(tmp_path)
    (ws / "three.txt").write_text("a\nb\nc\n")
    res = await execute_read_file(
        mgr,
        ReadFileInput(repository="alpha", file_path="three.txt", start_line=10, num_lines=5),
    )
    assert res["total_lines"] == 3
    assert res["start_line"] == 4  # total_lines + 1
    assert res["end_line"] == 3
    assert res["content"] == ""


async def test_read_file_repo_not_ready_when_no_git_dir(tmp_path: Path) -> None:
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
    mgr = RepositoryManager(settings)
    with pytest.raises(ToolError) as ei:
        await execute_read_file(mgr, ReadFileInput(repository="alpha", file_path="a.py"))
    assert ei.value.code == ErrorCode.REPO_NOT_READY
