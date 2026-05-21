"""Tests for `backends.git_ls.list_tracked_files`."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codesearch_mcp.backends.git_ls import list_tracked_files

from .fixtures import init_working_tree

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary required"),
]


async def test_list_tracked_files_returns_all_when_no_subpath(tmp_path: Path) -> None:
    init_working_tree(
        tmp_path,
        {"a.py": "1", "src/b.py": "2", "src/sub/c.py": "3"},
    )
    files = await list_tracked_files(tmp_path)
    assert set(files) == {"a.py", "src/b.py", "src/sub/c.py"}


async def test_list_tracked_files_respects_subpath(tmp_path: Path) -> None:
    """Passing ``subpath`` appends ``-- <subpath>`` to the argv (line 15)."""
    init_working_tree(
        tmp_path,
        {"a.py": "1", "src/b.py": "2", "src/sub/c.py": "3"},
    )
    files = await list_tracked_files(tmp_path, subpath="src")
    assert set(files) == {"src/b.py", "src/sub/c.py"}


async def test_list_tracked_files_returns_empty_for_unmatched_subpath(
    tmp_path: Path,
) -> None:
    """When the subpath matches no tracked file, stdout is empty and the
    function short-circuits with an empty list (line 19)."""
    init_working_tree(tmp_path, {"a.py": "1"})
    files = await list_tracked_files(tmp_path, subpath="does/not/exist")
    assert files == []
