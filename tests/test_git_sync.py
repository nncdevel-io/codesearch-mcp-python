"""Integration tests for clone / fetch / reset and failure isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.git_sync import sync_many, sync_one
from codesearch_mcp.repo.manager import RepositoryManager, RepositoryState, SyncOutcome

from .conftest import requires_git
from .fixtures import append_commit, make_remote_with_files

pytestmark = [pytest.mark.asyncio, requires_git]


def _settings_for(tmp_path: Path, repos: list[tuple[str, str]]) -> Settings:
    return Settings(
        repositories=[
            RepositoryConfig(
                id=rid,
                remote=remote,
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url=f"https://github.com/o/{rid}",
            )
            for rid, remote in repos
        ],
        workspace_root=str(tmp_path / "ws"),
    )


async def test_clone_then_fetch_picks_up_new_commits(tmp_path: Path) -> None:
    bare = make_remote_with_files(
        tmp_path / "bare.git",
        tmp_path / "work",
        {"src/a.py": "print('one')\n"},
    )
    settings = _settings_for(tmp_path, [("alpha", bare.url)])
    mgr = RepositoryManager(settings)

    rep = await sync_one(mgr, settings, "alpha")
    assert rep.success and rep.head_commit
    assert (mgr.workspace("alpha") / "src" / "a.py").read_text() == "print('one')\n"

    append_commit(tmp_path / "work", "src/a.py", "print('two')\n", "update")
    rep2 = await sync_one(mgr, settings, "alpha")
    assert rep2.success
    assert (mgr.workspace("alpha") / "src" / "a.py").read_text() == "print('two')\n"
    assert mgr.status("alpha").state is RepositoryState.READY


async def test_failure_isolated_between_repositories(tmp_path: Path) -> None:
    good = make_remote_with_files(
        tmp_path / "good.git",
        tmp_path / "good_work",
        {"README.md": "hi\n"},
    )
    settings = _settings_for(
        tmp_path,
        [
            ("good", good.url),
            ("broken", str(tmp_path / "does-not-exist.git")),
        ],
    )
    mgr = RepositoryManager(settings)
    reports = await sync_many(mgr, settings, timeout=30.0)
    by_id = {r.repository_id: r for r in reports}
    assert by_id["good"].success is True
    assert by_id["broken"].success is False
    assert mgr.status("good").state is RepositoryState.READY
    assert mgr.status("broken").state is RepositoryState.FAILED
    assert mgr.status("broken").last_outcome is SyncOutcome.FAILURE
