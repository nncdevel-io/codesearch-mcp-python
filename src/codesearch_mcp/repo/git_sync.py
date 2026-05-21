"""Per-repository git clone / fetch / reset with auth and failure isolation."""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..backends.command import base_env, run_checked, run_command
from ..config.models import AuthType, RepositoryConfig, SecretConfig, Settings
from ..errors import ErrorCode, ToolError
from .manager import RepositoryManager


@dataclass(slots=True)
class SyncReport:
    repository_id: str
    success: bool
    error: str | None = None
    head_commit: str | None = None


def _ssh_command_env(ssh_key_path: str) -> dict[str, str]:
    return {
        "GIT_SSH_COMMAND": (
            f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        ),
    }


def _remote_with_token(remote: str, token: str) -> str:
    if remote.startswith("https://"):
        return f"https://x-access-token:{token}@{remote.removeprefix('https://')}"
    if remote.startswith("http://"):
        return f"http://x-access-token:{token}@{remote.removeprefix('http://')}"
    return remote


def _env_for(secret: SecretConfig) -> dict[str, str]:
    extra: dict[str, str] = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
    }
    if secret.auth_type is AuthType.SSH_KEY and secret.ssh_key_path:
        extra.update(_ssh_command_env(secret.ssh_key_path))
    return base_env(extra)


def _effective_remote(repo: RepositoryConfig, secret: SecretConfig) -> str:
    if secret.auth_type is AuthType.TOKEN and secret.token:
        return _remote_with_token(repo.remote, secret.token)
    return repo.remote


async def _git(
    argv: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str],
    timeout: float | None = None,
) -> str:
    res = await run_checked(["git", *argv], cwd=cwd, env=env, timeout=timeout)
    return res.stdout.decode("utf-8", errors="replace").strip()


async def _git_raw(
    argv: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str],
    timeout: float | None = None,
) -> tuple[int, str, str]:
    res = await run_command(["git", *argv], cwd=cwd, env=env, timeout=timeout)
    return (
        res.returncode,
        res.stdout.decode("utf-8", errors="replace"),
        res.stderr.decode("utf-8", errors="replace"),
    )


async def clone_repository(
    repo: RepositoryConfig,
    workspace: Path,
    secret: SecretConfig,
    timeout: float = 600.0,
) -> str:
    """Clone the configured single branch into ``workspace``. Returns HEAD commit sha."""

    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists():
        shutil.rmtree(workspace)
    env = _env_for(secret)
    remote = _effective_remote(repo, secret)
    await _git(
        [
            "clone",
            "--branch",
            repo.branch,
            "--single-branch",
            "--depth",
            "1",
            remote,
            str(workspace),
        ],
        cwd=None,
        env=env,
        timeout=timeout,
    )
    return await _git(["rev-parse", "HEAD"], cwd=workspace, env=env, timeout=30.0)


async def update_repository(
    repo: RepositoryConfig,
    workspace: Path,
    secret: SecretConfig,
    timeout: float = 300.0,
) -> str:
    """Fetch and hard-reset the configured branch. Returns HEAD commit sha."""

    env = _env_for(secret)
    if not (workspace / ".git").exists():
        return await clone_repository(repo, workspace, secret, timeout=timeout)
    await _git(
        ["fetch", "--prune", "--depth", "1", "origin", repo.branch],
        cwd=workspace,
        env=env,
        timeout=timeout,
    )
    await _git(
        ["reset", "--hard", f"origin/{repo.branch}"],
        cwd=workspace,
        env=env,
        timeout=60.0,
    )
    return await _git(["rev-parse", "HEAD"], cwd=workspace, env=env, timeout=30.0)


async def sync_one(
    manager: RepositoryManager,
    settings: Settings,
    repo_id: str,
    timeout: float = 600.0,
) -> SyncReport:
    """Sync a single repository, isolating any failure to this repository."""

    repo = manager.config(repo_id)
    secret = settings.secret_for(repo_id)
    workspace = manager.workspace(repo_id)
    async with manager.lock_for(repo_id):
        try:
            commit = await update_repository(repo, workspace, secret, timeout=timeout)
        except ToolError as exc:
            manager.mark_failure(repo_id, exc.message)
            return SyncReport(repository_id=repo_id, success=False, error=exc.message)
        except Exception as exc:  # noqa: BLE001
            manager.mark_failure(repo_id, str(exc))
            return SyncReport(repository_id=repo_id, success=False, error=str(exc))
        manager.mark_success(repo_id, commit)
        return SyncReport(repository_id=repo_id, success=True, head_commit=commit)


async def sync_many(
    manager: RepositoryManager,
    settings: Settings,
    repo_ids: Iterable[str] | None = None,
    timeout: float = 600.0,
) -> list[SyncReport]:
    targets = list(repo_ids) if repo_ids is not None else manager.ids()
    # Sequential to avoid pounding the same remote and to keep failure isolation simple.
    reports: list[SyncReport] = []
    for rid in targets:
        try:
            reports.append(await sync_one(manager, settings, rid, timeout=timeout))
        except ToolError as exc:
            if exc.code is ErrorCode.REPO_NOT_FOUND:
                raise
            reports.append(SyncReport(repository_id=rid, success=False, error=exc.message))
    return reports
