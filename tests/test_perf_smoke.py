"""Performance smoke tests for spec §8 budgets.

The synthetic repository is deliberately ~5k files / ~80k lines: small enough
to run in CI seconds, large enough to exercise ripgrep's parallel scan path.
"""

from __future__ import annotations

import time

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.tools.list_files import execute_list_files
from codesearch_mcp.tools.list_tree import execute_list_tree
from codesearch_mcp.tools.read_file import execute_read_file
from codesearch_mcp.tools.schemas import (
    ListFilesInput,
    ListTreeInput,
    ReadFileInput,
    SearchCodeInput,
)
from codesearch_mcp.tools.search_code import execute_search_code

from .conftest import requires_git, requires_rg
from .fixtures import init_working_tree

pytestmark = [requires_git, requires_rg]


@pytest.fixture(scope="module")
def populated_repo(tmp_path_factory: pytest.TempPathFactory):
    tmp = tmp_path_factory.mktemp("perf")
    workspace = tmp / "ws" / "alpha"
    # ~5000 .py files with 16 lines each = ~80k lines
    files: dict[str, str] = {}
    for i in range(5000):
        sub = f"pkg_{i // 100:03d}"
        body: list[str] = []
        for j in range(8):
            body.append(f"def fn_{i}_{j}():")
            body.append(f"    return 'needle_{i % 7}'")
        files[f"src/{sub}/mod_{i:05d}.py"] = "\n".join(body) + "\n"
    files["README.md"] = "# perf smoke\n"
    init_working_tree(workspace, files)
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
        workspace_root=str(tmp / "ws"),
    )
    mgr = RepositoryManager(settings)
    mgr.mark_success("alpha", "smoke")
    return settings, mgr


async def test_search_code_under_budget(populated_repo) -> None:
    _, mgr = populated_repo
    payload = SearchCodeInput(pattern="needle_3", repository="alpha", max_results=50)
    start = time.monotonic()
    out = await execute_search_code(mgr, payload)
    elapsed = time.monotonic() - start
    assert out["total_matches"] > 0
    # Spec §5.1 search_code p95 ≤ 2.0s. We allow ample margin here.
    assert elapsed < 2.0, f"search_code took {elapsed:.3f}s"


async def test_list_files_under_budget(populated_repo) -> None:
    _, mgr = populated_repo
    payload = ListFilesInput(repository="alpha", pattern="**/*.py", max_results=500)
    start = time.monotonic()
    out = await execute_list_files(mgr, payload)
    elapsed = time.monotonic() - start
    assert len(out["files"]) > 0
    assert elapsed < 1.0, f"list_files took {elapsed:.3f}s"


async def test_list_tree_under_budget(populated_repo) -> None:
    _, mgr = populated_repo
    payload = ListTreeInput(repository="alpha", max_depth=3, max_entries=500)
    start = time.monotonic()
    out = await execute_list_tree(mgr, payload)
    elapsed = time.monotonic() - start
    assert out["entry_count"] > 0
    assert elapsed < 1.0, f"list_tree took {elapsed:.3f}s"


async def test_read_file_under_budget(populated_repo) -> None:
    _, mgr = populated_repo
    payload = ReadFileInput(repository="alpha", file_path="src/pkg_000/mod_00000.py", num_lines=50)
    start = time.monotonic()
    out = await execute_read_file(mgr, payload)
    elapsed = time.monotonic() - start
    assert out["total_lines"] > 0
    assert elapsed < 0.5, f"read_file took {elapsed:.3f}s"
