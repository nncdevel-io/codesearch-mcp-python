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


async def test_search_code_path_scope_normalizes(tmp_path: Path) -> None:
    """Passing a ``path`` argument routes through ``_normalize_subpath`` and
    constrains the search to that subdirectory (line 76)."""
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {"src/a.py": "needle\n", "other/b.py": "needle\n"},
    )
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")
    out = await execute_search_code(
        mgr,
        SearchCodeInput(
            pattern="needle",
            repository="alpha",
            path="src",
            output_mode="files_with_matches",
        ),
    )
    paths = {f["file_path"] for f in out["files"]}
    assert paths == {"src/a.py"}


async def test_search_code_context_lines_build_range_url(tmp_path: Path) -> None:
    """Context-before/after lines result in a range URL ``#Lstart-Lend``
    and the grouping attaches them to the nearest match (lines 93-101 + 174-176)."""
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {
            "src/a.py": "alpha\nbeta\nNEEDLE\ngamma\ndelta\n",
        },
    )
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")
    out = await execute_search_code(
        mgr,
        SearchCodeInput(
            pattern="NEEDLE",
            repository="alpha",
            context_before=2,
            context_after=2,
            case_sensitive=True,
        ),
    )
    assert out["total_matches"] == 1
    match = out["matches"][0]
    assert [c["line_number"] for c in match["context_before"]] == [1, 2]
    assert [c["line_number"] for c in match["context_after"]] == [4, 5]
    assert match["git_url"].endswith("src/a.py#L1-L5")


async def test_search_code_count_mode_respects_exclude(tmp_path: Path) -> None:
    """Count-mode filtering: files under an excluded prefix are dropped before
    sorting (line 147)."""
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {
            "src/a.py": "needle\nneedle\n",
            "vendor/b.py": "needle\nneedle\nneedle\n",
        },
    )
    mgr = _mgr(tmp_path, exclude=["vendor/"])
    mgr.mark_success("alpha", "x")
    out = await execute_search_code(
        mgr,
        SearchCodeInput(pattern="needle", repository="alpha", output_mode="count"),
    )
    files = {f["file_path"] for f in out["files"]}
    assert files == {"src/a.py"}


def test_group_contexts_skips_orphan_context_lines() -> None:
    """A context line whose ``file_path`` has no corresponding match (e.g. all
    matches in that file were truncated away) is silently dropped — defensive
    branch (line 95)."""
    from codesearch_mcp.backends.ripgrep import RgContextLine, RgMatch
    from codesearch_mcp.tools.search_code import _group_contexts_by_match

    matches = [RgMatch(file_path="a.py", line_number=10, line_content="hit")]
    contexts = [
        RgContextLine(file_path="orphan.py", line_number=1, content="lonely"),
        RgContextLine(file_path="a.py", line_number=9, content="before"),
    ]
    grouped = _group_contexts_by_match(matches, contexts)
    # Only the match in a.py registered — orphan.py context contributes nothing.
    assert set(grouped.keys()) == {("a.py", 10)}
    assert grouped[("a.py", 10)]["before"] == [{"line_number": 9, "content": "before"}]


async def test_search_code_generic_rg_failure_is_backend_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ripgrep exits with code 2 but stderr does NOT mention regex parse
    error, the tool surfaces ``BACKEND_FAILURE`` (line 65, the ``or`` short-
    circuit's false leg + the unconditional raise)."""
    from codesearch_mcp.backends.command import CommandResult
    from codesearch_mcp.tools import search_code as sc_mod

    init_working_tree(tmp_path / "ws" / "alpha", {"a.py": "x"})
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")

    async def fake_run(*args: object, **kwargs: object) -> CommandResult:
        return CommandResult(returncode=2, stdout=b"", stderr=b"some other rg error\n")

    monkeypatch.setattr(sc_mod, "run_command", fake_run)
    with pytest.raises(ToolError) as ei:
        await execute_search_code(mgr, SearchCodeInput(pattern="needle", repository="alpha"))
    assert ei.value.code is ErrorCode.BACKEND_FAILURE


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


async def test_list_files_excludes_configured_paths(tmp_path: Path) -> None:
    """``exclude_paths`` in the repository config filters out matched files
    (lines 32-33 in ``_excluded``)."""
    ws = tmp_path / "ws" / "alpha"
    init_working_tree(
        ws,
        {"src/a.py": "x", "vendor/b.py": "y"},
    )
    mgr = _mgr(tmp_path, exclude=["vendor/"])
    mgr.mark_success("alpha", "x")
    out = await execute_list_files(mgr, ListFilesInput(repository="alpha", pattern="**/*.py"))
    paths = {f["file_path"] for f in out["files"]}
    assert paths == {"src/a.py"}


async def test_list_files_invalid_glob_pattern_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ripgrep returns code 2 with a glob-error stderr, the tool surfaces
    ``INVALID_PATTERN`` (lines 50-56)."""
    from codesearch_mcp.backends.command import CommandResult
    from codesearch_mcp.tools import list_files as lf_mod

    init_working_tree(tmp_path / "ws" / "alpha", {"a.py": "x"})
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")

    async def fake_run(*args: object, **kwargs: object) -> CommandResult:
        return CommandResult(returncode=2, stdout=b"", stderr=b"glob parse error: bad\n")

    monkeypatch.setattr(lf_mod, "run_command", fake_run)
    with pytest.raises(ToolError) as ei:
        await execute_list_files(mgr, ListFilesInput(repository="alpha", pattern="[oops"))
    assert ei.value.code is ErrorCode.INVALID_PATTERN


async def test_list_files_other_rg_failure_is_backend_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ripgrep code 2 without a glob-error stderr maps to ``BACKEND_FAILURE``
    (line 57)."""
    from codesearch_mcp.backends.command import CommandResult
    from codesearch_mcp.tools import list_files as lf_mod

    init_working_tree(tmp_path / "ws" / "alpha", {"a.py": "x"})
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")

    async def fake_run(*args: object, **kwargs: object) -> CommandResult:
        return CommandResult(returncode=2, stdout=b"", stderr=b"unrelated rg failure\n")

    monkeypatch.setattr(lf_mod, "run_command", fake_run)
    with pytest.raises(ToolError) as ei:
        await execute_list_files(mgr, ListFilesInput(repository="alpha", pattern="*.py"))
    assert ei.value.code is ErrorCode.BACKEND_FAILURE


async def test_list_files_skips_disappearing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that vanishes between ripgrep's listing and the ``stat`` call is
    silently dropped (lines 71-72: FileNotFoundError)."""
    from codesearch_mcp.backends.command import CommandResult
    from codesearch_mcp.tools import list_files as lf_mod

    init_working_tree(tmp_path / "ws" / "alpha", {"a.py": "x"})
    mgr = _mgr(tmp_path)
    mgr.mark_success("alpha", "x")

    # ripgrep "found" a file that does not actually exist on disk.
    async def fake_run(*args: object, **kwargs: object) -> CommandResult:
        return CommandResult(returncode=0, stdout=b"./ghost.py\n./a.py\n", stderr=b"")

    monkeypatch.setattr(lf_mod, "run_command", fake_run)
    out = await execute_list_files(mgr, ListFilesInput(repository="alpha", pattern="**/*.py"))
    files = {f["file_path"] for f in out["files"]}
    assert "ghost.py" not in files
    assert "a.py" in files
