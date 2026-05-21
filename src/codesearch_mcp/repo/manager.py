"""Repository state, workspace paths, sync result tracking (TASK-011 / TASK-028)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from ..config.models import RepositoryConfig, Settings
from ..errors import ErrorCode, ToolError


class RepositoryState(StrEnum):
    UNINITIALIZED = "uninitialized"
    READY = "ready"
    FAILED = "failed"


class SyncOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(slots=True)
class SyncStatus:
    repository_id: str
    state: RepositoryState
    last_outcome: SyncOutcome | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None
    last_commit: str | None = None


@dataclass(slots=True)
class _Entry:
    config: RepositoryConfig
    workspace: Path
    status: SyncStatus
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RepositoryManager:
    """Holds per-repository workspace paths, readiness, and last sync status."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        root = Path(settings.workspace_root).expanduser().resolve()
        self._workspace_root = root
        self._entries: dict[str, _Entry] = {}
        for repo in settings.repositories:
            workspace = root / repo.id
            initial = (
                RepositoryState.READY
                if (workspace / ".git").exists()
                else RepositoryState.UNINITIALIZED
            )
            self._entries[repo.id] = _Entry(
                config=repo,
                workspace=workspace,
                status=SyncStatus(repository_id=repo.id, state=initial),
            )

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def ids(self) -> list[str]:
        return list(self._entries.keys())

    def configs(self) -> list[RepositoryConfig]:
        return [e.config for e in self._entries.values()]

    def config(self, repo_id: str) -> RepositoryConfig:
        return self._require(repo_id).config

    def workspace(self, repo_id: str) -> Path:
        return self._require(repo_id).workspace

    def status(self, repo_id: str) -> SyncStatus:
        return self._require(repo_id).status

    def all_status(self) -> list[SyncStatus]:
        return [e.status for e in self._entries.values()]

    def require_ready(self, repo_id: str) -> Path:
        entry = self._require(repo_id)
        if entry.status.state is not RepositoryState.READY:
            raise ToolError(
                ErrorCode.REPO_NOT_READY,
                "repository workspace is not ready",
                {"repository": repo_id, "state": entry.status.state.value},
            )
        return entry.workspace

    def lock_for(self, repo_id: str) -> asyncio.Lock:
        return self._require(repo_id).lock

    def mark_success(self, repo_id: str, commit: str | None) -> None:
        e = self._require(repo_id)
        e.status.state = RepositoryState.READY
        e.status.last_outcome = SyncOutcome.SUCCESS
        e.status.last_sync_at = datetime.now(UTC)
        e.status.last_commit = commit
        e.status.last_error = None

    def mark_failure(self, repo_id: str, error: str) -> None:
        e = self._require(repo_id)
        was_ready = e.status.state is RepositoryState.READY or (e.workspace / ".git").exists()
        e.status.state = RepositoryState.READY if was_ready else RepositoryState.FAILED
        e.status.last_outcome = SyncOutcome.FAILURE
        e.status.last_sync_at = datetime.now(UTC)
        e.status.last_error = error

    def _require(self, repo_id: str) -> _Entry:
        entry = self._entries.get(repo_id)
        if entry is None:
            raise ToolError(
                ErrorCode.REPO_NOT_FOUND,
                "repository is not configured",
                {"repository": repo_id},
            )
        return entry
