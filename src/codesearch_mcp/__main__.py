"""Command line entry points: ``codesearch-mcp`` (serve) and ``codesearch-sync``."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path

from .config.loader import (
    ConfigError,
    discover_server_config_path,
    load_server_config,
    load_settings,
)
from .config.models import ServerConfig, Settings
from .logging import configure_logging, log_event
from .observability import sync_status_report
from .repo.git_sync import sync_many
from .repo.manager import RepositoryManager
from .repo.notify import notify_serve_if_running, remove_serve_pid, write_serve_pid
from .repo.scheduler import SyncScheduler
from .server import build_server


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repos", help="path to repos.toml (or set CODE_SEARCH_REPOS_PATH)")
    parser.add_argument("--secrets", help="path to secrets.toml (or set CODE_SEARCH_SECRETS_PATH)")
    parser.add_argument(
        "--workspace-root",
        help="workspace root directory (or set CODE_SEARCH_WORKSPACE_ROOT)",
    )


def _resolve_settings(
    *,
    repos_arg: str | None,
    secrets_arg: str | None,
    workspace_arg: str | None,
) -> Settings:
    """Resolve repository/secret/workspace paths and load the validated Settings."""
    return load_settings(
        repos_arg=repos_arg,
        secrets_arg=secrets_arg,
        workspace_arg=workspace_arg,
    )


def _resolve_server_config(
    *,
    config_arg: str | None,
    transport: str | None,
    host: str | None,
    port: int | None,
    enable_scheduler: bool | None,
) -> ServerConfig:
    """Load config/server.toml and overlay CLI flags (CLI wins)."""
    path, explicit = discover_server_config_path(config_arg)
    base = load_server_config(path, required=explicit)
    return base.overlay_cli(
        transport=transport,
        host=host,
        port=port,
        enable_scheduler=enable_scheduler,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codesearch-mcp")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the MCP server")
    serve.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=None,
        help="transport (overrides config/server.toml)",
    )
    serve.add_argument("--host", default=None, help="bind host (overrides config/server.toml)")
    serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="bind port (overrides config/server.toml)",
    )
    serve.add_argument(
        "--enable-scheduler",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable the in-process periodic sync scheduler (overrides config/server.toml)",
    )
    serve.add_argument(
        "--config",
        help=(
            "path to server config TOML (or set CODE_SEARCH_CONFIG_PATH); "
            "defaults to ./config/server.toml when present"
        ),
    )
    _add_config_args(serve)

    sync = sub.add_parser("sync", help="synchronise repositories once and exit")
    sync.add_argument("--repository", action="append", help="limit sync to this id (repeatable)")
    _add_config_args(sync)

    status = sub.add_parser("status", help="print the sync status report as JSON")
    _add_config_args(status)
    return parser


def _install_sighup_refresh(manager: RepositoryManager) -> None:
    """Wire SIGHUP → ``manager.refresh_states_from_disk`` on platforms that support it."""
    if not hasattr(signal, "SIGHUP"):
        return
    loop = asyncio.get_running_loop()

    def _handle() -> None:
        log_event("info", "sighup_received", action="refresh_states_from_disk")
        manager.refresh_states_from_disk()

    loop.add_signal_handler(signal.SIGHUP, _handle)


async def _run_serve(settings: Settings, server_cfg: ServerConfig) -> int:
    workspace_root = Path(settings.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    manager = RepositoryManager(settings)
    write_serve_pid(workspace_root)
    _install_sighup_refresh(manager)
    log_event(
        "info",
        "server_start",
        transport=server_cfg.transport.value,
        repositories=manager.ids(),
        scheduler=server_cfg.enable_scheduler,
    )
    server = build_server(settings, manager, host=server_cfg.host, port=server_cfg.port)

    scheduler = SyncScheduler(manager, settings) if server_cfg.enable_scheduler else None
    if scheduler:
        scheduler.start()
    try:
        if server_cfg.transport.value == "stdio":
            await server.run_stdio_async()
        else:
            # FastMCP exposes Streamable HTTP via run_streamable_http_async.
            await server.run_streamable_http_async()
    finally:
        if scheduler:
            await scheduler.stop()
        remove_serve_pid(workspace_root)
    return 0


async def _run_sync(settings: Settings, repo_ids: list[str] | None) -> int:
    workspace_root = Path(settings.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    manager = RepositoryManager(settings)
    reports = await sync_many(manager, settings, repo_ids=repo_ids)
    failures = [r for r in reports if not r.success]
    payload = [
        {
            "repository": r.repository_id,
            "success": r.success,
            "head_commit": r.head_commit,
            "error": r.error,
        }
        for r in reports
    ]
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    # Best-effort: nudge a running serve to refresh its in-memory readiness
    # so newly-cloned workspaces become queryable without a restart.
    notify_serve_if_running(workspace_root)
    return 1 if failures else 0


async def _run_status(settings: Settings) -> int:
    manager = RepositoryManager(settings)
    sys.stdout.write(json.dumps(sync_status_report(manager), ensure_ascii=False, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            settings = _resolve_settings(
                repos_arg=args.repos,
                secrets_arg=args.secrets,
                workspace_arg=args.workspace_root,
            )
            server_cfg = _resolve_server_config(
                config_arg=args.config,
                transport=args.transport,
                host=args.host,
                port=args.port,
                enable_scheduler=args.enable_scheduler,
            )
            return asyncio.run(_run_serve(settings, server_cfg))
        if args.command == "sync":
            settings = _resolve_settings(
                repos_arg=args.repos,
                secrets_arg=args.secrets,
                workspace_arg=args.workspace_root,
            )
            return asyncio.run(_run_sync(settings, args.repository))
        if args.command == "status":
            settings = _resolve_settings(
                repos_arg=args.repos,
                secrets_arg=args.secrets,
                workspace_arg=args.workspace_root,
            )
            return asyncio.run(_run_status(settings))
    except ConfigError as err:
        sys.stderr.write(f"config error: {err}\n")
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


def sync_main(argv: list[str] | None = None) -> int:
    """Entry point for the ``codesearch-sync`` console script."""

    configure_logging()
    parser = argparse.ArgumentParser(prog="codesearch-sync")
    parser.add_argument(
        "--repository",
        action="append",
        help="limit sync to this id (repeatable)",
    )
    _add_config_args(parser)
    args = parser.parse_args(argv)
    try:
        settings = _resolve_settings(
            repos_arg=args.repos,
            secrets_arg=args.secrets,
            workspace_arg=args.workspace_root,
        )
        return asyncio.run(_run_sync(settings, args.repository))
    except ConfigError as err:
        sys.stderr.write(f"config error: {err}\n")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
