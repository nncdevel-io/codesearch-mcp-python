"""Tests for the list_tree ASCII formatter and tool."""

from __future__ import annotations

from pathlib import Path

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.tools.list_tree import build_tree_text, execute_list_tree
from codesearch_mcp.tools.schemas import ListTreeInput

from .conftest import requires_git
from .fixtures import init_working_tree


def test_build_tree_text_simple() -> None:
    text, truncated, count = build_tree_text(
        [
            "src/main/java/com/example/A.java",
            "src/main/java/com/example/B.java",
            "src/test/java/com/example/ATest.java",
            "README.md",
        ],
        root_label="repo",
        max_depth=5,
        show_files=True,
        max_entries=100,
    )
    assert not truncated
    assert text.startswith("repo/\n")
    assert "├── README.md" in text or "└── README.md" in text
    assert "│   ├── " in text or "│   └── " in text
    assert count > 0


def test_build_tree_text_respects_max_depth() -> None:
    text, _, _ = build_tree_text(
        ["a/b/c/d/e.txt"],
        root_label="r",
        max_depth=2,
        show_files=True,
        max_entries=100,
    )
    assert "c/" not in text  # depth 3 not rendered
    assert "b/" in text  # depth 2 rendered


def test_build_tree_text_show_files_false_hides_files() -> None:
    text, _, _ = build_tree_text(
        ["src/a.py", "src/sub/b.py", "README.md"],
        root_label="r",
        max_depth=5,
        show_files=False,
        max_entries=100,
    )
    assert "README.md" not in text
    assert "src/" in text
    assert "sub/" in text


def test_build_tree_text_truncates() -> None:
    paths = [f"d/{i:03d}.txt" for i in range(20)]
    text, truncated, count = build_tree_text(
        paths,
        root_label="r",
        max_depth=5,
        show_files=True,
        max_entries=5,
    )
    assert truncated is True
    assert count == 5


def test_build_tree_text_code_point_order() -> None:
    text, _, _ = build_tree_text(
        ["Z.txt", "a.txt", "B.txt"],
        root_label="r",
        max_depth=1,
        show_files=True,
        max_entries=100,
    )
    body = text.splitlines()
    # 'B' < 'Z' < 'a' in code point order
    order = [line.split("── ", 1)[1] for line in body[1:]]
    assert order == ["B.txt", "Z.txt", "a.txt"]


def test_build_tree_text_skips_empty_path_entries() -> None:
    """Empty strings in the input list are skipped silently (line 49)."""
    text, _, count = build_tree_text(
        ["", "a.py", ""],
        root_label="r",
        max_depth=2,
        show_files=True,
        max_entries=100,
    )
    assert "a.py" in text
    assert count == 1


def test_build_tree_text_excludes_prefix_matches() -> None:
    """``exclude_prefixes`` filters matched entries before insertion (line 53)."""
    text, _, _ = build_tree_text(
        ["src/a.py", "vendor/b.py", "vendor/sub/c.py"],
        root_label="r",
        max_depth=5,
        show_files=True,
        max_entries=100,
        exclude_prefixes=("vendor/",),
    )
    assert "vendor" not in text
    assert "a.py" in text


@requires_git
async def test_execute_list_tree_rejects_file_path(tmp_path: Path) -> None:
    """Passing a file path (not a directory) as ``path`` raises
    ``PATH_NOT_FOUND`` (lines 95-97)."""
    import pytest

    from codesearch_mcp.errors import ErrorCode, ToolError

    workspace = tmp_path / "ws" / "alpha"
    init_working_tree(workspace, {"src/a.py": "x"})
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
    mgr.mark_success("alpha", "deadbeef")
    with pytest.raises(ToolError) as ei:
        await execute_list_tree(mgr, ListTreeInput(repository="alpha", path="src/a.py"))
    assert ei.value.code is ErrorCode.PATH_NOT_FOUND


@requires_git
async def test_execute_list_tree_strips_subpath_prefix(tmp_path: Path) -> None:
    """When ``path`` is provided, files inside it are listed with the prefix
    stripped (lines 105-106)."""
    workspace = tmp_path / "ws" / "alpha"
    init_working_tree(
        workspace,
        {"src/a.py": "1", "src/sub/b.py": "2", "README.md": "z"},
    )
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
    mgr.mark_success("alpha", "deadbeef")
    out = await execute_list_tree(mgr, ListTreeInput(repository="alpha", path="src", max_depth=3))
    # README.md was in the parent and must not appear in the subtree.
    assert "README.md" not in out["tree"]
    # The prefix ``src/`` is stripped from each entry, so we see ``a.py`` at root.
    assert "a.py" in out["tree"]
    assert "sub/" in out["tree"]


@requires_git
async def test_execute_list_tree_filters_untracked(tmp_path: Path) -> None:
    workspace = tmp_path / "ws" / "alpha"
    init_working_tree(workspace, {"src/a.py": "x", "README.md": "y"})
    # Untracked file must be excluded:
    (workspace / "untracked.log").write_text("noise")
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
    mgr.mark_success("alpha", "deadbeef")
    out = await execute_list_tree(mgr, ListTreeInput(repository="alpha", max_depth=3))
    assert "untracked.log" not in out["tree"]
    assert "README.md" in out["tree"]
    assert out["entry_count"] >= 2
