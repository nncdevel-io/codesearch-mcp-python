"""Tests for the SIGHUP-based sync→serve notification bridge."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager, RepositoryState
from codesearch_mcp.repo.notify import (
    notify_serve_if_running,
    remove_serve_pid,
    serve_pid_path,
    write_serve_pid,
)


def _settings(workspace_root: Path) -> Settings:
    return Settings(
        repositories=[
            RepositoryConfig(
                id="a",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/a",
            ),
        ],
        workspace_root=str(workspace_root),
    )


def test_refresh_upgrades_uninitialized_to_ready_after_clone(tmp_path: Path) -> None:
    manager = RepositoryManager(_settings(tmp_path))
    assert manager.status("a").state is RepositoryState.UNINITIALIZED

    # Simulate an external clone landing on disk.
    (tmp_path / "a" / ".git").mkdir(parents=True)

    manager.refresh_states_from_disk()
    assert manager.status("a").state is RepositoryState.READY


def test_refresh_is_noop_when_workspace_still_empty(tmp_path: Path) -> None:
    manager = RepositoryManager(_settings(tmp_path))
    manager.refresh_states_from_disk()
    assert manager.status("a").state is RepositoryState.UNINITIALIZED


def _seed_minimal_git_dir(workspace: Path, commit_hash: str = "a" * 40) -> Path:
    """Lay down enough .git structure to look like a real clone.

    `.git/HEAD` → `ref: refs/heads/main`, `.git/refs/heads/main` → commit hash,
    `.git/FETCH_HEAD` → set the mtime via a touch.
    """
    git_dir = workspace / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "refs" / "heads" / "main").write_text(f"{commit_hash}\n")
    (git_dir / "FETCH_HEAD").write_text("")
    return git_dir


def test_refresh_enriches_last_commit_from_disk(tmp_path: Path) -> None:
    manager = RepositoryManager(_settings(tmp_path))
    commit = "1234567890abcdef" * 2 + "12345678"  # 40 hex chars
    _seed_minimal_git_dir(tmp_path / "a", commit_hash=commit)

    manager.refresh_states_from_disk()
    status = manager.status("a")
    assert status.state is RepositoryState.READY
    assert status.last_commit == commit
    assert status.last_sync_at is not None


def test_init_enriches_last_commit_when_clone_pre_existed(tmp_path: Path) -> None:
    commit = "deadbeef" * 5  # 40 hex chars
    _seed_minimal_git_dir(tmp_path / "a", commit_hash=commit)
    manager = RepositoryManager(_settings(tmp_path))
    status = manager.status("a")
    assert status.state is RepositoryState.READY
    assert status.last_commit == commit
    assert status.last_sync_at is not None


def test_refresh_does_not_downgrade_ready(tmp_path: Path) -> None:
    (tmp_path / "a" / ".git").mkdir(parents=True)
    manager = RepositoryManager(_settings(tmp_path))
    assert manager.status("a").state is RepositoryState.READY

    # Even if .git transiently disappears, the manager refuses to downgrade
    # based on a half-baked filesystem check.
    import shutil

    shutil.rmtree(tmp_path / "a" / ".git")
    manager.refresh_states_from_disk()
    assert manager.status("a").state is RepositoryState.READY


def test_write_serve_pid_writes_current_pid_atomically(tmp_path: Path) -> None:
    path = write_serve_pid(tmp_path)
    assert path == serve_pid_path(tmp_path)
    assert int(path.read_text().strip()) == os.getpid()
    # Tmp file should be cleaned up by rename.
    assert not (tmp_path / f"{path.name}.tmp").exists()


def test_remove_serve_pid_is_idempotent(tmp_path: Path) -> None:
    write_serve_pid(tmp_path)
    remove_serve_pid(tmp_path)
    assert not serve_pid_path(tmp_path).exists()
    # Second call must not raise.
    remove_serve_pid(tmp_path)


def test_notify_returns_false_without_pid_file(tmp_path: Path) -> None:
    assert notify_serve_if_running(tmp_path) is False


def test_notify_returns_false_on_unparseable_pid(tmp_path: Path) -> None:
    serve_pid_path(tmp_path).write_text("not-an-int\n")
    assert notify_serve_if_running(tmp_path) is False


def test_notify_returns_false_when_process_is_gone(tmp_path: Path) -> None:
    # PID 2**31 - 1 is well above typical max_pid; ESRCH is the expected error.
    serve_pid_path(tmp_path).write_text(f"{2**31 - 1}\n")
    assert notify_serve_if_running(tmp_path) is False


def test_notify_returns_false_when_platform_lacks_sighup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On platforms without ``SIGHUP`` (Windows), notification silently
    no-ops (line 59). Simulated by deleting the attribute."""
    import codesearch_mcp.repo.notify as notify_mod

    monkeypatch.delattr(notify_mod.signal, "SIGHUP", raising=False)
    assert notify_mod.notify_serve_if_running(tmp_path) is False


def test_notify_reraises_unexpected_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``os.kill`` raising an OSError whose errno is not ESRCH/EPERM is *not*
    swallowed — it re-raises so the caller learns of the unexpected condition
    (line 72: ``raise``)."""
    import codesearch_mcp.repo.notify as notify_mod

    serve_pid_path(tmp_path).write_text("12345\n")

    def fake_kill(pid: int, sig: int) -> None:
        raise OSError(99, "unexpected")

    monkeypatch.setattr(notify_mod.os, "kill", fake_kill)
    with pytest.raises(OSError):
        notify_mod.notify_serve_if_running(tmp_path)


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="SIGHUP not supported")
def test_notify_actually_signals_running_process(tmp_path: Path) -> None:
    received: list[int] = []

    def handler(signum: int, _frame: object) -> None:
        received.append(signum)

    old = signal.signal(signal.SIGHUP, handler)
    try:
        write_serve_pid(tmp_path)  # writes our own PID
        assert notify_serve_if_running(tmp_path) is True
        # Give the kernel a moment to deliver the signal.
        deadline = time.monotonic() + 1.0
        while not received and time.monotonic() < deadline:
            time.sleep(0.01)
        assert received == [signal.SIGHUP]
    finally:
        signal.signal(signal.SIGHUP, old)
