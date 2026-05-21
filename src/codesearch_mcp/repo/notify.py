"""PID file + best-effort SIGHUP between external ``codesearch-sync`` and serve.

External ``codesearch-sync`` runs in a separate process from ``codesearch-mcp
serve``, so its sync results cannot directly mutate the running server's
``RepositoryManager``. We bridge the two via a tiny Unix-idiomatic protocol:

- ``serve`` writes its PID atomically to ``<workspace_root>/.serve.pid`` at
  startup and removes it at shutdown.
- ``codesearch-sync`` reads that PID after a successful sync and sends
  ``SIGHUP`` (best effort). The server's signal handler calls
  :meth:`RepositoryManager.refresh_states_from_disk`.

If the PID file is missing, unreadable, points at a dead process, or the
platform lacks ``SIGHUP`` (Windows), notification silently no-ops — the
user can still restart the server to pick up new clones.
"""

from __future__ import annotations

import errno
import os
import signal
from pathlib import Path

from ..logging import log_event

PID_FILE_NAME = ".serve.pid"


def serve_pid_path(workspace_root: Path) -> Path:
    return workspace_root / PID_FILE_NAME


def write_serve_pid(workspace_root: Path) -> Path:
    """Write the current PID atomically (write-temp-then-rename)."""
    path = serve_pid_path(workspace_root)
    tmp = path.parent / f"{path.name}.tmp"
    tmp.write_text(f"{os.getpid()}\n")
    tmp.replace(path)
    return path


def remove_serve_pid(workspace_root: Path) -> None:
    """Best-effort removal of the PID file (idempotent)."""
    try:
        serve_pid_path(workspace_root).unlink()
    except FileNotFoundError:
        pass


def notify_serve_if_running(workspace_root: Path) -> bool:
    """Send SIGHUP to the serve identified by the PID file. Best effort.

    Returns ``True`` only when the signal was actually delivered. Silently
    returns ``False`` on missing/unparseable PID file, dead/foreign process,
    or platforms without ``SIGHUP`` (Windows).
    """
    if not hasattr(signal, "SIGHUP"):
        return False
    path = serve_pid_path(workspace_root)
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, signal.SIGHUP)
    except OSError as exc:
        # ESRCH: process is gone. EPERM: process exists but is not ours
        # (stale PID file, recycled PID). Treat both as "no serve to notify".
        if exc.errno in {errno.ESRCH, errno.EPERM}:
            return False
        raise
    log_event(
        "info",
        "serve_notified",
        pid=pid,
        workspace_root=str(workspace_root),
    )
    return True


__all__ = [
    "PID_FILE_NAME",
    "notify_serve_if_running",
    "remove_serve_pid",
    "serve_pid_path",
    "write_serve_pid",
]
