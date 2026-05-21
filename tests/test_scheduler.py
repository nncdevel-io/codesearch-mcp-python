"""Tests for the optional in-process sync scheduler."""

from __future__ import annotations

import asyncio
import logging as stdlib_logging
from pathlib import Path

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo import scheduler as scheduler_mod
from codesearch_mcp.repo.git_sync import SyncReport
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.repo.scheduler import SyncScheduler

pytestmark = pytest.mark.asyncio


def _build_manager(tmp_path: Path, interval: int = 60) -> tuple[RepositoryManager, Settings]:
    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="alpha",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/alpha",
                refresh_interval_seconds=interval,
            )
        ],
        workspace_root=str(tmp_path / "ws"),
    )
    return RepositoryManager(settings), settings


async def test_scheduler_start_runs_sync_and_stop_cancels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Start the scheduler, observe one ``scheduled_sync`` log entry, then stop.

    Covers: task creation, _loop body executing, log_event on success,
    stop() cancellation path (asyncio.CancelledError swallow)."""
    mgr, settings = _build_manager(tmp_path)
    calls: list[str] = []
    done = asyncio.Event()

    async def fake_sync_one(_mgr: object, _settings: object, repo_id: str) -> SyncReport:
        calls.append(repo_id)
        done.set()
        return SyncReport(repository_id=repo_id, success=True, head_commit="abcdef")

    monkeypatch.setattr(scheduler_mod, "sync_one", fake_sync_one)

    scheduler = SyncScheduler(mgr, settings)
    with caplog.at_level(stdlib_logging.INFO, logger="codesearch_mcp"):
        scheduler.start()
        # Idempotent: a redundant ``start()`` while tasks exist must be a no-op.
        scheduler.start()
        assert len(scheduler._tasks) == 1
        await asyncio.wait_for(done.wait(), timeout=2.0)
        await scheduler.stop()
    assert calls == ["alpha"]
    assert any(getattr(rec, "ctx", {}).get("event") == "scheduled_sync" for rec in caplog.records)


async def test_scheduler_logs_warning_on_failed_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed ``SyncReport`` triggers a ``warning``-level scheduled_sync log
    (covers the ``success=False`` arm of the level-selection ternary)."""
    mgr, settings = _build_manager(tmp_path)
    done = asyncio.Event()

    async def fake_sync_one(_mgr: object, _settings: object, repo_id: str) -> SyncReport:
        done.set()
        return SyncReport(repository_id=repo_id, success=False, error="fetch failed")

    monkeypatch.setattr(scheduler_mod, "sync_one", fake_sync_one)

    scheduler = SyncScheduler(mgr, settings)
    with caplog.at_level(stdlib_logging.WARNING, logger="codesearch_mcp"):
        scheduler.start()
        await asyncio.wait_for(done.wait(), timeout=2.0)
        await scheduler.stop()
    warnings = [
        rec
        for rec in caplog.records
        if rec.levelno == stdlib_logging.WARNING
        and getattr(rec, "ctx", {}).get("event") == "scheduled_sync"
    ]
    assert warnings


async def test_scheduler_logs_error_on_unexpected_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When ``sync_one`` raises a non-CancelledError exception, the scheduler
    logs ``scheduler_unexpected_error`` and continues looping."""
    mgr, settings = _build_manager(tmp_path)
    done = asyncio.Event()

    async def fake_sync_one(_mgr: object, _settings: object, repo_id: str) -> SyncReport:
        done.set()
        raise RuntimeError("kaboom")

    monkeypatch.setattr(scheduler_mod, "sync_one", fake_sync_one)

    scheduler = SyncScheduler(mgr, settings)
    with caplog.at_level(stdlib_logging.ERROR, logger="codesearch_mcp"):
        scheduler.start()
        await asyncio.wait_for(done.wait(), timeout=2.0)
        await scheduler.stop()
    assert any(
        getattr(rec, "ctx", {}).get("event") == "scheduler_unexpected_error"
        for rec in caplog.records
    )


async def test_scheduler_stop_logs_unexpected_task_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """If a scheduled task raises an unexpected error during shutdown (after
    the cancel signal), ``stop()`` logs ``scheduler_shutdown_error`` (lines
    44-50)."""
    mgr, settings = _build_manager(tmp_path)

    async def fake_sync_one(*args: object, **kwargs: object) -> SyncReport:
        raise RuntimeError("ignored — overridden below")

    monkeypatch.setattr(scheduler_mod, "sync_one", fake_sync_one)

    scheduler = SyncScheduler(mgr, settings)

    # Replace the scheduler's tasks with one that raises a non-CancelledError
    # when awaited. We bypass start() to keep the test deterministic.
    async def _bad() -> None:
        raise RuntimeError("shutdown boom")

    bad_task = asyncio.create_task(_bad(), name="sync-alpha")
    # Let the task complete (errored) so the await in stop() sees the exception.
    await asyncio.sleep(0)
    scheduler._tasks.append(bad_task)

    with caplog.at_level(stdlib_logging.WARNING, logger="codesearch_mcp"):
        await scheduler.stop()
    assert any(
        getattr(rec, "ctx", {}).get("event") == "scheduler_shutdown_error" for rec in caplog.records
    )


async def test_scheduler_loop_exits_naturally_when_stop_event_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``self._stop`` is set without an explicit ``task.cancel()``, the
    inner ``await wait_for`` returns and the next ``while`` check falls
    through (branch 56→exit)."""
    mgr, settings = _build_manager(tmp_path)
    seen = asyncio.Event()

    async def fake_sync_one(_mgr: object, _settings: object, repo_id: str) -> SyncReport:
        seen.set()
        return SyncReport(repository_id=repo_id, success=True, head_commit=None)

    monkeypatch.setattr(scheduler_mod, "sync_one", fake_sync_one)

    scheduler = SyncScheduler(mgr, settings)
    scheduler.start()
    task = scheduler._tasks[0]
    # Wait for one iteration, then signal stop without cancelling — the loop
    # should exit normally on the next ``while`` check.
    await asyncio.wait_for(seen.wait(), timeout=2.0)
    scheduler._stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert task.done() and not task.cancelled()
    scheduler._tasks.clear()


async def test_scheduler_reraises_cancelled_error_from_sync_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``sync_one`` itself raises ``asyncio.CancelledError`` (e.g. because
    ``task.cancel()`` interrupted it mid-await), the scheduler's
    ``except asyncio.CancelledError: raise`` path lets it propagate (line 68)."""
    mgr, settings = _build_manager(tmp_path)
    started = asyncio.Event()

    async def fake_sync_one(_mgr: object, _settings: object, repo_id: str) -> SyncReport:
        started.set()
        raise asyncio.CancelledError("simulated cancel during sync")

    monkeypatch.setattr(scheduler_mod, "sync_one", fake_sync_one)

    scheduler = SyncScheduler(mgr, settings)
    scheduler.start()
    task = scheduler._tasks[0]
    await asyncio.wait_for(started.wait(), timeout=2.0)
    # The task should observe the re-raised CancelledError and finish.
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)
    scheduler._tasks.clear()


async def test_scheduler_loop_observes_stop_signal_via_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the interval elapses without the stop signal, ``asyncio.wait_for``
    raises ``TimeoutError`` and the loop continues (lines 77-79).

    We can't realistically wait the 60-second minimum ``refresh_interval``,
    so we patch ``scheduler_mod.asyncio.wait_for`` to raise ``TimeoutError``
    immediately, forcing the loop to iterate."""
    mgr, settings = _build_manager(tmp_path)
    iterations = 0
    seen_two = asyncio.Event()

    async def fake_sync_one(_mgr: object, _settings: object, repo_id: str) -> SyncReport:
        nonlocal iterations
        iterations += 1
        if iterations >= 2:
            seen_two.set()
        return SyncReport(repository_id=repo_id, success=True, head_commit=None)

    monkeypatch.setattr(scheduler_mod, "sync_one", fake_sync_one)

    async def fast_timeout(coro: object, timeout: float) -> object:
        # Close the wrapped coroutine to avoid "never awaited" warnings, then
        # raise TimeoutError so the scheduler hits its ``except TimeoutError``
        # branch and loops.
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[attr-defined]
        await asyncio.sleep(0)
        raise TimeoutError

    monkeypatch.setattr(scheduler_mod.asyncio, "wait_for", fast_timeout)

    scheduler = SyncScheduler(mgr, settings)
    scheduler.start()
    try:
        # ``asyncio.wait_for`` is now patched globally, so we poll the event
        # manually with our own deadline.
        for _ in range(500):  # ~5 s @ 10 ms cadence
            if seen_two.is_set():
                break
            await asyncio.sleep(0.01)
        assert seen_two.is_set(), "scheduler did not iterate twice in time"
    finally:
        await scheduler.stop()
    assert iterations >= 2
