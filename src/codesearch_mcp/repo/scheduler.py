"""Optional in-process scheduler for periodic git synchronization (TASK-029)."""

from __future__ import annotations

import asyncio
from typing import Any

from ..config.models import Settings
from ..logging import log_event
from .git_sync import sync_one
from .manager import RepositoryManager


class SyncScheduler:
    """Per-repository asyncio loop that triggers ``sync_one`` at the configured interval.

    Disabled by default; callers must explicitly call ``start``. The scheduler
    never blocks tool execution: it runs in its own tasks.
    """

    def __init__(self, manager: RepositoryManager, settings: Settings) -> None:
        self._manager = manager
        self._settings = settings
        self._tasks: list[asyncio.Task[Any]] = []
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._tasks:
            return
        self._stop.clear()
        for repo_id in self._manager.ids():
            task = asyncio.create_task(self._loop(repo_id), name=f"sync-{repo_id}")
            self._tasks.append(task)

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                log_event(
                    "warning",
                    "scheduler_shutdown_error",
                    task=task.get_name(),
                    error=str(exc),
                )
        self._tasks.clear()

    async def _loop(self, repo_id: str) -> None:
        cfg = self._manager.config(repo_id)
        interval = max(1, cfg.refresh_interval_seconds)
        while not self._stop.is_set():
            try:
                report = await sync_one(self._manager, self._settings, repo_id)
                log_event(
                    "info" if report.success else "warning",
                    "scheduled_sync",
                    repository=repo_id,
                    success=report.success,
                    head_commit=report.head_commit,
                    error=report.error,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log_event(
                    "error",
                    "scheduler_unexpected_error",
                    repository=repo_id,
                    error=str(exc),
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                continue
