"""Integration tests for the search_code and list_files tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.errors import ErrorCode, ToolError
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.tools.list_files import execute_list_files
from codesearch_mcp.tools.schemas import ListFilesInput, SearchCodeInput
from codesearch_mcp.tools.search_code import execute_search_code

from .conftest import requires_git, requires_rg
from .fixtures import init_working_tree

pytestmark = [requires_git, requires_rg]


def _mgr(tmp_path: Path, exclude: list[str] | None = None) -> RepositoryManager:
    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="alpha",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/alpha",
                exclude_paths=exclude or [],
            )
        ],
        workspace_root=str(tmp_path / "ws"),
    )
    mgr = RepositoryManager(settings)
    return mgr


async def test_search_code_content_mode(tmp_path: Path) -> None:
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {
            "src/a.py": "def hello():\n    return 'world'\n",
            "src/b.py": "def bye():\n    return 'world'\n",
        },
    )
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")
    out = await execute_search_code(mgr, SearchCodeInput(pattern="hello", repository="alpha"))
    assert out["total_matches"] >= 1
    paths = {m["file_path"] for m in out["matches"]}
    assert "src/a.py" in paths
    assert out["matches"][0]["git_url"].endswith("src/a.py#L1")


async def test_search_code_files_with_matches_mode(tmp_path: Path) -> None:
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {
            "src/a.py": "needle\n",
            "src/b.py": "haystack\n",
            "src/c.py": "needle\n",
        },
    )
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")
    out = await execute_search_code(
        mgr,
        SearchCodeInput(pattern="needle", repository="alpha", output_mode="files_with_matches"),
    )
    files = sorted(f["file_path"] for f in out["files"])
    assert files == ["src/a.py", "src/c.py"]


async def test_search_code_count_mode(tmp_path: Path) -> None:
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {
            "src/a.py": "needle\nneedle\nneedle\n",
            "src/b.py": "needle\n",
        },
    )
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")
    out = await execute_search_code(
        mgr,
        SearchCodeInput(pattern="needle", repository="alpha", output_mode="count"),
    )
    counts = {f["file_path"]: f["match_count"] for f in out["files"]}
    assert counts["src/a.py"] == 3
    assert counts["src/b.py"] == 1


async def test_search_code_invalid_pattern_raises(tmp_path: Path) -> None:
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(ws, {"a.py": "x\n"})
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")
    with pytest.raises(ToolError) as ei:
        await execute_search_code(mgr, SearchCodeInput(pattern="(", repository="alpha"))
    assert ei.value.code == ErrorCode.INVALID_PATTERN


async def test_search_code_excludes_configured_paths(tmp_path: Path) -> None:
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {"src/a.py": "needle\n", "vendor/b.py": "needle\n"},
    )
    mgr = _mgr(tmp_path, exclude=["vendor/"])
    mgr.mark_success("alpha", "x")
    out = await execute_search_code(
        mgr,
        SearchCodeInput(pattern="needle", repository="alpha", output_mode="files_with_matches"),
    )
    paths = {f["file_path"] for f in out["files"]}
    assert paths == {"src/a.py"}


async def test_list_files_returns_matches_with_metadata(tmp_path: Path) -> None:
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {
            "src/main/A.java": "class A {}\n",
            "src/test/ATest.java": "class T {}\n",
            "README.md": "# r\n",
        },
    )
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")
    out = await execute_list_files(mgr, ListFilesInput(repository="alpha", pattern="**/*.java"))
    paths = {f["file_path"] for f in out["files"]}
    assert paths == {"src/main/A.java", "src/test/ATest.java"}
    for f in out["files"]:
        assert "last_modified" in f
        assert f["git_url"].endswith(f["file_path"] + "#L1")
