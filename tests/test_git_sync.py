"""Integration tests for clone / fetch / reset and failure isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesearch_mcp.config.models import AuthType, RepositoryConfig, SecretConfig, Settings
from codesearch_mcp.errors import ErrorCode, ToolError
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo import git_sync as git_sync_mod
from codesearch_mcp.repo.git_sync import (
    _effective_remote,
    _env_for,
    _remote_with_token,
    _ssh_command_env,
    sync_many,
    sync_one,
)
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


async def test_ssh_command_env_builds_strict_options() -> None:
    """``_ssh_command_env`` emits a ``GIT_SSH_COMMAND`` with explicit identity,
    IdentitiesOnly, and accept-new host policy (line 25)."""
    env = _ssh_command_env("/keys/id_rsa")
    cmd = env["GIT_SSH_COMMAND"]
    assert "ssh -i /keys/id_rsa" in cmd
    assert "IdentitiesOnly=yes" in cmd
    assert "StrictHostKeyChecking=accept-new" in cmd


async def test_remote_with_token_injects_into_http_and_https() -> None:
    """``_remote_with_token`` injects ``x-access-token`` into both http and
    https URLs and leaves other schemes alone (lines 33-36)."""
    assert (
        _remote_with_token("https://github.com/o/r.git", "tok")
        == "https://x-access-token:tok@github.com/o/r.git"
    )
    assert (
        _remote_with_token("http://example.com/r.git", "tok")
        == "http://x-access-token:tok@example.com/r.git"
    )
    # SSH / git+ssh URLs pass through unchanged.
    assert _remote_with_token("git@github.com:o/r.git", "tok") == "git@github.com:o/r.git"


async def test_env_for_ssh_secret_includes_ssh_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_env_for`` adds ``GIT_SSH_COMMAND`` only for ``AuthType.SSH_KEY`` with
    a populated ``ssh_key_path`` (line 46)."""
    monkeypatch.delenv("LC_ALL", raising=False)
    secret = SecretConfig(auth_type=AuthType.SSH_KEY, ssh_key_path="/keys/id_rsa")
    env = _env_for(secret)
    assert "GIT_SSH_COMMAND" in env
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    # The ``none``-auth case must NOT inject GIT_SSH_COMMAND.
    none_env = _env_for(SecretConfig(auth_type=AuthType.NONE))
    assert "GIT_SSH_COMMAND" not in none_env


async def test_effective_remote_uses_token_for_token_auth() -> None:
    """``_effective_remote`` returns the token-rewritten URL when the secret is
    ``AuthType.TOKEN`` with a populated ``token`` (line 52)."""
    repo = RepositoryConfig(
        id="r",
        remote="https://github.com/o/r.git",
        branch="main",
        hosting=Hosting.GITHUB,
        hosting_base_url="https://github.com/o/r",
    )
    secret = SecretConfig(auth_type=AuthType.TOKEN, token="tok")
    assert _effective_remote(repo, secret).startswith("https://x-access-token:tok@")
    # No secret → returns the raw remote.
    assert _effective_remote(repo, SecretConfig(auth_type=AuthType.NONE)) == repo.remote


async def test_clone_removes_pre_existing_workspace(tmp_path: Path) -> None:
    """``clone_repository`` deletes a stale workspace before cloning fresh
    (line 92)."""
    bare = make_remote_with_files(
        tmp_path / "bare.git",
        tmp_path / "work",
        {"a.txt": "1\n"},
    )
    settings = _settings_for(tmp_path, [("alpha", bare.url)])
    mgr = RepositoryManager(settings)
    ws = mgr.workspace("alpha")
    # Plant a non-git file so we can detect that the rmtree path was taken.
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "stale.txt").write_text("from previous run")
    rep = await sync_one(mgr, settings, "alpha")
    assert rep.success
    assert not (ws / "stale.txt").exists()
    assert (ws / "a.txt").exists()


async def test_sync_one_wraps_unexpected_exception_as_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-``ToolError`` raised inside ``update_repository`` is converted
    into a failure ``SyncReport`` with ``mark_failure`` called (lines 156-158)."""
    settings = _settings_for(tmp_path, [("alpha", "/does/not/matter")])
    mgr = RepositoryManager(settings)

    async def boom(*args: object, **kwargs: object) -> str:
        raise RuntimeError("disk full")

    monkeypatch.setattr(git_sync_mod, "update_repository", boom)
    rep = await sync_one(mgr, settings, "alpha")
    assert rep.success is False
    assert rep.error == "disk full"
    assert mgr.status("alpha").state is RepositoryState.FAILED


async def test_sync_many_reraises_repo_not_found(tmp_path: Path) -> None:
    """``sync_many`` re-raises ``REPO_NOT_FOUND`` (programmer error), but
    records other ``ToolError`` as a failure report (lines 175-178)."""
    bare = make_remote_with_files(
        tmp_path / "bare.git",
        tmp_path / "work",
        {"a.txt": "1\n"},
    )
    settings = _settings_for(tmp_path, [("alpha", bare.url)])
    mgr = RepositoryManager(settings)
    with pytest.raises(ToolError) as ei:
        await sync_many(mgr, settings, repo_ids=["nope"], timeout=10.0)
    assert ei.value.code is ErrorCode.REPO_NOT_FOUND


async def test_sync_many_records_other_tool_errors_as_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-REPO_NOT_FOUND ``ToolError`` raised by ``sync_one`` is captured
    into the per-repo report instead of bubbling (line 178)."""
    settings = _settings_for(tmp_path, [("alpha", "/x")])
    mgr = RepositoryManager(settings)

    async def fake_sync_one(_mgr: object, _settings: object, rid: str, **kw: object) -> object:
        raise ToolError(ErrorCode.BACKEND_FAILURE, "fetch broke", {})

    monkeypatch.setattr(git_sync_mod, "sync_one", fake_sync_one)
    reports = await sync_many(mgr, settings, repo_ids=["alpha"], timeout=10.0)
    assert reports[0].success is False
    assert reports[0].error == "fetch broke"


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
