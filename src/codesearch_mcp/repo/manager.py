"""Repository state, workspace paths, sync result tracking (TASK-011 / TASK-028)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from ..config.models import RepositoryConfig, Settings
from ..errors import ErrorCode, ToolError

_HEX_DIGITS = frozenset("0123456789abcdef")


class RepositoryState(StrEnum):
    UNINITIALIZED = "uninitialized"
    READY = "ready"
    FAILED = "failed"


class SyncOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(slots=True)
class SyncStatus:
    # Ordered for human readability: identity → current state → when →
    # result → reason → current head. Programs do not depend on this.
    repository_id: str
    state: RepositoryState
    last_sync_at: datetime | None = None
    last_outcome: SyncOutcome | None = None
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
            entry = _Entry(
                config=repo,
                workspace=workspace,
                status=SyncStatus(repository_id=repo.id, state=initial),
            )
            self._entries[repo.id] = entry
            # When the workspace already has a clone, derive last_commit
            # and last_sync_at straight from .git (no subprocess). This
            # lets serve restarts and SIGHUP refreshes report meaningful
            # metadata without depending on the previous in-process sync.
            if initial is RepositoryState.READY:
                _enrich_status_from_git(entry)

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

    def refresh_states_from_disk(self) -> None:
        """Re-read each entry's status from on-disk ``.git`` contents.

        Entry point used by the SIGHUP handler so an external
        ``codesearch-sync`` run can publish its results to a running
        serve without a restart. For every entry:

        - If ``.git`` exists, the entry becomes (or stays) ``ready``, and
          ``last_commit`` / ``last_sync_at`` are re-derived from the
          on-disk repository (HEAD ref and FETCH_HEAD / HEAD mtime).
        - If ``.git`` is missing, the entry's state is left alone — a
          half-baked filesystem check is not used to downgrade a previously
          ``ready`` workspace (transient FS hiccups would cause flapping).

        ``last_outcome`` / ``last_error`` are not derivable from the git
        workspace alone, so they are not touched here; they reflect the
        most recent in-process ``mark_success`` / ``mark_failure``.
        """
        for entry in self._entries.values():
            if (entry.workspace / ".git").exists():
                if entry.status.state is not RepositoryState.READY:
                    entry.status.state = RepositoryState.READY
                _enrich_status_from_git(entry)

    def _require(self, repo_id: str) -> _Entry:
        entry = self._entries.get(repo_id)
        if entry is None:
            raise ToolError(
                ErrorCode.REPO_NOT_FOUND,
                "repository is not configured",
                {"repository": repo_id},
            )
        return entry


def _enrich_status_from_git(entry: _Entry) -> None:
    """Populate ``last_commit`` / ``last_sync_at`` from on-disk ``.git`` contents.

    No subprocess: we read the loose / packed ref directly. Any parse
    failure or missing file is a silent no-op so a partially-cloned or
    unusual workspace does not crash the manager. Existing values are
    only overwritten when a fresh disk-derived value is available.
    """
    git_dir = entry.workspace / ".git"
    commit = _read_head_commit(git_dir)
    if commit is not None:
        entry.status.last_commit = commit
    sync_at = _read_last_sync_at(git_dir)
    if sync_at is not None:
        entry.status.last_sync_at = sync_at


def _read_head_commit(git_dir: Path) -> str | None:
    """Resolve ``.git/HEAD`` to a 40-char commit hash, or ``None`` on failure."""
    try:
        head = (git_dir / "HEAD").read_text().strip()
    except OSError:
        return None
    if head.startswith("ref: "):
        ref_name = head[5:].strip()
        # Loose ref first.
        try:
            value = (git_dir / ref_name).read_text().strip()
        except OSError:
            value = None
        if _looks_like_sha1(value):
            return value
        # Fall back to packed-refs (git gc may have packed the symref's target).
        try:
            packed = (git_dir / "packed-refs").read_text()
        except OSError:
            return None
        for line in packed.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "^")):
                continue
            parts = stripped.split(maxsplit=1)
            if len(parts) == 2 and parts[1] == ref_name and _looks_like_sha1(parts[0]):
                return parts[0]
        return None
    return head if _looks_like_sha1(head) else None


def _read_last_sync_at(git_dir: Path) -> datetime | None:
    """mtime of FETCH_HEAD (set by fetch) → fall back to HEAD (set by clone)."""
    for name in ("FETCH_HEAD", "HEAD"):
        candidate = git_dir / name
        try:
            return datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
        except OSError:
            continue
    return None


def _looks_like_sha1(value: str | None) -> bool:
    if value is None or len(value) != 40:
        return False
    return all(c in _HEX_DIGITS for c in value.lower())
