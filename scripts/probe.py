"""Reference MCP client for verifying a running codesearch-mcp instance.

Useful when an MCP host application (Claude Code, Claude Desktop, ...) is not
available and you just want to confirm "the server is alive and the tools work".

Examples
--------

Probe a Streamable HTTP server (e.g. the docker-compose example)::

    uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/

List the advertised tools without invoking any of them::

    uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ --list

Invoke a specific tool. Arguments use ``key=value`` pairs (JSON-decoded so you
can pass numbers and booleans)::

    uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ \\
        --tool search_code \\
        --arg pattern=needle \\
        --arg repository=main-app \\
        --arg max_results=5

Probe a stdio-launched server in-process. Pass the launch command after
``--stdio --``::

    uv run python scripts/probe.py --stdio -- \\
        uv run codesearch-mcp serve --transport stdio --repos ./examples/repos.toml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--url",
        help="Streamable HTTP endpoint URL (e.g. http://127.0.0.1:8000/mcp/).",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Spawn a stdio server using the command after '--'.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Only list advertised tools; do not invoke any.",
    )
    parser.add_argument(
        "--tool",
        default="search_code",
        help="Name of the tool to invoke (default: search_code).",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Tool argument (repeatable). VALUE is parsed as JSON when possible.",
    )
    parser.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="With --stdio, the command (after '--') to launch the server.",
    )
    ns = parser.parse_args()
    if not ns.stdio and not ns.url:
        parser.error("either URL or --stdio is required")
    return ns


def _parse_kv(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in pairs:
        if "=" not in raw:
            raise SystemExit(f"--arg must be KEY=VALUE: {raw!r}")
        key, _, val = raw.partition("=")
        try:
            out[key] = json.loads(val)
        except json.JSONDecodeError:
            out[key] = val
    return out


async def _run_session(session: Any, args: argparse.Namespace) -> int:
    await session.initialize()
    tools = await session.list_tools()
    print("Tools advertised:")
    for tool in tools.tools:
        first_line = (tool.description or "").splitlines()[0] if tool.description else ""
        print(f"  - {tool.name}: {first_line[:80]}")
    if args.list:
        return 0

    matching = next((t for t in tools.tools if t.name == args.tool), None)
    if matching is None:
        print(f"\nERROR: tool {args.tool!r} not advertised by server", file=sys.stderr)
        return 2

    arguments = _parse_kv(args.arg)
    print(f"\nCalling {args.tool} with arguments: {arguments}")
    result = await session.call_tool(args.tool, arguments)
    print(f"isError: {result.isError}")
    for block in result.content:
        text = getattr(block, "text", None)
        if text is not None:
            print(text)
    return 1 if result.isError else 0


async def _probe_http(url: str, args: argparse.Namespace) -> int:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            return await _run_session(session, args)


async def _probe_stdio(command: list[str], args: argparse.Namespace) -> int:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    if not command:
        raise SystemExit("--stdio requires a command after '--'")
    params = StdioServerParameters(command=command[0], args=command[1:])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            return await _run_session(session, args)


def main() -> int:
    args = _parse_args()
    if args.stdio:
        cmd = [a for a in args.rest if a != "--"]
        return asyncio.run(_probe_stdio(cmd, args))
    return asyncio.run(_probe_http(args.url, args))


if __name__ == "__main__":
    raise SystemExit(main())
