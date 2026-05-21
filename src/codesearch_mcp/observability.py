"""Observability helpers — report last sync time/result per repository (TASK-028)."""

from __future__ import annotations

from typing import Any

from .repo.manager import RepositoryManager


def sync_status_report(manager: RepositoryManager) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for status in manager.all_status():
        report.append(
            {
                # identity → current state → when → result → reason → head
                "repository": status.repository_id,
                "state": status.state.value,
                "last_sync_at": status.last_sync_at.isoformat().replace("+00:00", "Z")
                if status.last_sync_at
                else None,
                "last_outcome": status.last_outcome.value if status.last_outcome else None,
                "last_error": status.last_error,
                "last_commit": status.last_commit,
            }
        )
    return report
