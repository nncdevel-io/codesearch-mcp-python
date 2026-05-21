"""Tests for RepositoryManager state and isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.errors import ErrorCode, ToolError
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager, RepositoryState, SyncOutcome


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        repositories=[
            RepositoryConfig(
                id="alpha",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/a",
            ),
            RepositoryConfig(
                id="beta",
                remote="y",
                branch="main",
                hosting=Hosting.GITLAB,
                hosting_base_url="https://gitlab.com/o/b",
            ),
        ],
        workspace_root=str(tmp_path / "ws"),
    )


def test_workspaces_and_ids(tmp_path: Path) -> None:
    mgr = RepositoryManager(_settings(tmp_path))
    assert mgr.ids() == ["alpha", "beta"]
    assert mgr.workspace("alpha") == (tmp_path / "ws" / "alpha").resolve()


def test_unknown_repo_raises_repo_not_found(tmp_path: Path) -> None:
    mgr = RepositoryManager(_settings(tmp_path))
    with pytest.raises(ToolError) as ei:
        mgr.workspace("missing")
    assert ei.value.code == ErrorCode.REPO_NOT_FOUND


def test_require_ready_blocks_until_marked(tmp_path: Path) -> None:
    mgr = RepositoryManager(_settings(tmp_path))
    with pytest.raises(ToolError) as ei:
        mgr.require_ready("alpha")
    assert ei.value.code == ErrorCode.REPO_NOT_READY
    mgr.mark_success("alpha", "abc123")
    assert mgr.require_ready("alpha") == (tmp_path / "ws" / "alpha").resolve()
    assert mgr.status("alpha").state is RepositoryState.READY
    assert mgr.status("alpha").last_outcome is SyncOutcome.SUCCESS


def test_failure_after_success_keeps_workspace_readable(tmp_path: Path) -> None:
    mgr = RepositoryManager(_settings(tmp_path))
    mgr.mark_success("alpha", "deadbeef")
    mgr.mark_failure("alpha", "fetch failed")
    # Already-cloned repos should remain usable on a later fetch failure.
    assert mgr.status("alpha").state is RepositoryState.READY
    assert mgr.status("alpha").last_outcome is SyncOutcome.FAILURE
    assert mgr.status("alpha").last_error == "fetch failed"


def test_other_repo_not_affected_by_failure(tmp_path: Path) -> None:
    mgr = RepositoryManager(_settings(tmp_path))
    mgr.mark_failure("alpha", "boom")
    # beta is untouched
    assert mgr.status("beta").state is RepositoryState.UNINITIALIZED
    assert mgr.status("beta").last_error is None
