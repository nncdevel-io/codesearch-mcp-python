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


def test_workspace_root_and_configs_accessors(tmp_path: Path) -> None:
    """``workspace_root`` and ``configs()`` expose the resolved root path and
    config list — small accessors but part of the manager's public surface."""
    mgr = RepositoryManager(_settings(tmp_path))
    assert mgr.workspace_root == (tmp_path / "ws").resolve()
    configs = mgr.configs()
    assert [c.id for c in configs] == ["alpha", "beta"]


def test_mark_failure_on_uninitialized_keeps_failed_state(tmp_path: Path) -> None:
    """``mark_failure`` on an entry that has never been ready and has no
    on-disk ``.git`` → state becomes ``FAILED`` (lines 190-191 in survey,
    corresponds to ``state = FAILED if not was_ready``)."""
    mgr = RepositoryManager(_settings(tmp_path))
    mgr.mark_failure("alpha", "clone refused")
    assert mgr.status("alpha").state is RepositoryState.FAILED
    assert mgr.status("alpha").last_outcome is SyncOutcome.FAILURE
    assert mgr.status("alpha").last_error == "clone refused"


def test_refresh_re_enriches_already_ready_entry(tmp_path: Path) -> None:
    """When ``refresh_states_from_disk`` finds an entry already in ``READY``
    state with on-disk ``.git``, the state assignment is skipped (branch
    147→149) but the enrichment still runs."""
    (tmp_path / "ws" / "alpha" / ".git" / "refs" / "heads").mkdir(parents=True)
    (tmp_path / "ws" / "alpha" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / "ws" / "alpha" / ".git" / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    (tmp_path / "ws" / "alpha" / ".git" / "FETCH_HEAD").write_text("")
    mgr = RepositoryManager(_settings(tmp_path))
    # Constructor already set state to READY and enriched from disk.
    assert mgr.status("alpha").state is RepositoryState.READY
    first_commit = mgr.status("alpha").last_commit
    # Now rewrite the loose ref and refresh: state stays READY (branch 147→149
    # exits without re-assigning) but commit picks up the new value.
    (tmp_path / "ws" / "alpha" / ".git" / "refs" / "heads" / "main").write_text("b" * 40 + "\n")
    mgr.refresh_states_from_disk()
    assert mgr.status("alpha").state is RepositoryState.READY
    assert mgr.status("alpha").last_commit == "b" * 40
    assert mgr.status("alpha").last_commit != first_commit


def test_enrich_falls_back_to_packed_refs(tmp_path: Path) -> None:
    """When the loose ref file is absent, ``_read_head_commit`` falls back to
    parsing ``packed-refs`` (lines 195-206) — simulating a ``git gc``-packed
    workspace."""
    git_dir = tmp_path / "ws" / "alpha" / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    # No loose ref — write only packed-refs.
    commit = "c" * 40
    (git_dir / "packed-refs").write_text(
        f"# pack-refs with: peeled fully-peeled\n{commit} refs/heads/main\n"
    )
    (git_dir / "FETCH_HEAD").write_text("")
    mgr = RepositoryManager(_settings(tmp_path))
    assert mgr.status("alpha").last_commit == commit


def test_enrich_packed_refs_missing_returns_none(tmp_path: Path) -> None:
    """Both loose ref AND packed-refs missing → ``_read_head_commit`` returns
    ``None`` and ``last_commit`` stays unset (lines 197-198 OSError path)."""
    git_dir = tmp_path / "ws" / "alpha" / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    # No loose ref, no packed-refs.
    (git_dir / "FETCH_HEAD").write_text("")
    mgr = RepositoryManager(_settings(tmp_path))
    # State still becomes READY (because .git exists) but no commit was found.
    assert mgr.status("alpha").state is RepositoryState.READY
    assert mgr.status("alpha").last_commit is None


def test_enrich_packed_refs_skips_unrelated_lines(tmp_path: Path) -> None:
    """``packed-refs`` lines starting with ``#`` or ``^`` are skipped, and
    entries whose ref name does not match are ignored (line 202 + 205-206
    no-match)."""
    git_dir = tmp_path / "ws" / "alpha" / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "packed-refs").write_text(
        "# header\n"
        "^badnothex refs/heads/main\n"  # ^-prefixed: skip
        "deadbeef0000000000000000000000000000face refs/heads/other\n"  # wrong ref name
        "\n"  # blank
    )
    (git_dir / "FETCH_HEAD").write_text("")
    mgr = RepositoryManager(_settings(tmp_path))
    assert mgr.status("alpha").last_commit is None


def test_head_pointing_to_non_hex_returns_none(tmp_path: Path) -> None:
    """Detached HEAD with a non-hex content returns ``None`` rather than the
    raw string (line 223: ``_looks_like_sha1`` false leg via non-hex)."""
    git_dir = tmp_path / "ws" / "alpha" / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("zzzz not a sha1\n")
    (git_dir / "FETCH_HEAD").write_text("")
    mgr = RepositoryManager(_settings(tmp_path))
    assert mgr.status("alpha").last_commit is None
