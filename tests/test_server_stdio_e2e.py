"""End-to-end tests using the in-memory MCP client (equivalent to stdio dispatch)."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.server import build_server

from .conftest import requires_git, requires_rg
from .fixtures import init_working_tree

pytestmark = [requires_git, requires_rg]


def _settings(tmp_path: Path) -> tuple[Settings, RepositoryManager, Path]:
    workspace = tmp_path / "ws" / "alpha"
    init_working_tree(
        workspace,
        {
            "src/a.py": "def needle():\n    return 'one'\n",
            "src/b.py": "def haystack():\n    return 'two'\n",
            "README.md": "# title\n",
        },
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
    mgr.mark_success("alpha", "abc123")
    return settings, mgr, workspace


async def test_lists_five_tools(tmp_path: Path) -> None:
    settings, mgr, _ = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert names == {
            "search_code",
            "list_files",
            "list_tree",
            "read_file",
            "list_repositories",
        }


async def test_search_code_via_mcp(tmp_path: Path) -> None:
    settings, mgr, _ = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool(
            "search_code",
            {"pattern": "needle", "repository": "alpha"},
        )
        assert result.isError is False
        payload = result.structuredContent or json.loads(result.content[0].text)
        assert payload["total_matches"] >= 1
        paths = {m["file_path"] for m in payload["matches"]}
        assert "src/a.py" in paths


async def test_read_file_via_mcp(tmp_path: Path) -> None:
    settings, mgr, _ = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool(
            "read_file",
            {"repository": "alpha", "file_path": "README.md"},
        )
        assert result.isError is False
        payload = result.structuredContent or json.loads(result.content[0].text)
        assert payload["total_lines"] == 1
        assert payload["content"].endswith("# title\n")


async def test_invalid_path_returns_isError(tmp_path: Path) -> None:
    settings, mgr, _ = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool(
            "read_file",
            {"repository": "alpha", "file_path": "../escape"},
        )
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["code"] == "INVALID_PATH"


async def test_invalid_repo_returns_isError(tmp_path: Path) -> None:
    settings, mgr, _ = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool(
            "list_tree",
            {"repository": "missing"},
        )
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["code"] == "REPO_NOT_FOUND"


async def test_list_tree_via_mcp(tmp_path: Path) -> None:
    settings, mgr, _ = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool(
            "list_tree",
            {"repository": "alpha", "max_depth": 3},
        )
        assert result.isError is False
        payload = result.structuredContent or json.loads(result.content[0].text)
        assert "README.md" in payload["tree"]
        assert payload["entry_count"] >= 2


async def test_list_files_via_mcp(tmp_path: Path) -> None:
    settings, mgr, _ = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool(
            "list_files",
            {"repository": "alpha", "pattern": "**/*.py"},
        )
        assert result.isError is False
        payload = result.structuredContent or json.loads(result.content[0].text)
        paths = sorted(f["file_path"] for f in payload["files"])
        assert paths == ["src/a.py", "src/b.py"]
