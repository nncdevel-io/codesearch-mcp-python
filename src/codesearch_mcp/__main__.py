"""Command line entry points: ``codesearch-mcp`` (serve) and ``codesearch-sync``."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config.loader import ConfigError, discover_config_paths, load_settings
from .config.models import Settings
from .logging import configure_logging, log_event
from .observability import sync_status_report
from .repo.git_sync import sync_many
from .repo.manager import RepositoryManager
from .repo.scheduler import SyncScheduler
from .server import build_server


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repos", help="path to repos.toml (or set CODE_SEARCH_REPOS_PATH)")
    parser.add_argument("--secrets", help="path to secrets.toml (or set CODE_SEARCH_SECRETS_PATH)")
    parser.add_argument(
        "--workspace-root",
        help="workspace root directory (or set CODE_SEARCH_WORKSPACE_ROOT)",
    )


def _resolve_settings(args: argparse.Namespace) -> Settings:
    repos_path, secrets_path, workspace_root = discover_config_paths(
        args.repos, args.secrets, args.workspace_root
    )
    return load_settings(repos_path, secrets_path, workspace_root)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codesearch-mcp")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the MCP server")
    serve.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--enable-scheduler",
        action="store_true",
        help="enable the in-process periodic sync scheduler",
    )
    _add_config_args(serve)

    sync = sub.add_parser("sync", help="synchronise repositories once and exit")
    sync.add_argument("--repository", action="append", help="limit sync to this id (repeatable)")
    _add_config_args(sync)

    status = sub.add_parser("status", help="print the sync status report as JSON")
    _add_config_args(status)
    return parser


async def _run_serve(args: argparse.Namespace) -> int:
    settings = _resolve_settings(args)
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    manager = RepositoryManager(settings)
    log_event(
        "info",
        "server_start",
        transport=args.transport,
        repositories=manager.ids(),
        scheduler=args.enable_scheduler,
    )
    server = build_server(settings, manager)

    scheduler = SyncScheduler(manager, settings) if args.enable_scheduler else None
    if scheduler:
        scheduler.start()
    try:
        if args.transport == "stdio":
            await server.run_stdio_async()
        else:
            # FastMCP exposes Streamable HTTP via run_streamable_http_async.
            await server.run_streamable_http_async()
    finally:
        if scheduler:
            await scheduler.stop()
    return 0


async def _run_sync(args: argparse.Namespace) -> int:
    settings = _resolve_settings(args)
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    manager = RepositoryManager(settings)
    reports = await sync_many(manager, settings, repo_ids=args.repository)
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
    return 1 if failures else 0


async def _run_status(args: argparse.Namespace) -> int:
    settings = _resolve_settings(args)
    manager = RepositoryManager(settings)
    sys.stdout.write(json.dumps(sync_status_report(manager), ensure_ascii=False, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            return asyncio.run(_run_serve(args))
        if args.command == "sync":
            return asyncio.run(_run_sync(args))
        if args.command == "status":
            return asyncio.run(_run_status(args))
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
        return asyncio.run(_run_sync(args))
    except ConfigError as err:
        sys.stderr.write(f"config error: {err}\n")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
