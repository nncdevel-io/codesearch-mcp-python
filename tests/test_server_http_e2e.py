"""End-to-end test against the Streamable HTTP transport."""

from __future__ import annotations

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.server import build_server

from .conftest import requires_git, requires_rg
from .fixtures import init_working_tree


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    """Localhost test endpoints must not be routed through any HTTP proxy."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    for var in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        monkeypatch.delenv(var, raising=False)


pytestmark = [requires_git, requires_rg]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _serve(server, host: str, port: int):
    config = uvicorn.Config(
        server.streamable_http_app(),
        host=host,
        port=port,
        log_level="warning",
        loop="asyncio",
        lifespan="on",
    )
    uvi = uvicorn.Server(config)
    task = asyncio.create_task(uvi.serve())
    try:
        # Wait for server to be ready
        for _ in range(50):
            if uvi.started:
                break
            await asyncio.sleep(0.05)
        yield
    finally:
        uvi.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (TimeoutError, Exception):
            task.cancel()


async def test_http_transport_search_code(tmp_path: Path) -> None:
    workspace = tmp_path / "ws" / "alpha"
    init_working_tree(
        workspace,
        {"src/a.py": "def needle():\n    return 1\n"},
    )
    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="alpha",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/alpha",
            )
        ],
        workspace_root=str(tmp_path / "ws"),
    )
    mgr = RepositoryManager(settings)
    mgr.mark_success("alpha", "x")
    port = _free_port()
    server = build_server(settings, mgr, host="127.0.0.1", port=port)
    url = f"http://127.0.0.1:{port}/mcp/"

    async with _serve(server, "127.0.0.1", port):
        async with streamablehttp_client(url) as (reader, writer, _get_id):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert {"search_code", "list_files", "list_tree", "read_file"} <= names
                result = await session.call_tool(
                    "search_code",
                    {"pattern": "needle", "repository": "alpha"},
                )
                assert result.isError is False
                payload = result.structuredContent or json.loads(result.content[0].text)
                paths = {m["file_path"] for m in payload["matches"]}
                assert "src/a.py" in paths
