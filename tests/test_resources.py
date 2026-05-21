"""End-to-end tests for the repository catalog Resources."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.resources import repo_uri
from codesearch_mcp.server import build_server


def _settings(tmp_path: Path) -> tuple[Settings, RepositoryManager]:
    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="alpha",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/alpha",
                description="Frontend Vue.js shop app. Pages under src/views/.",
            ),
            RepositoryConfig(
                id="beta",
                remote="y",
                branch="develop",
                hosting=Hosting.GITLAB,
                hosting_base_url="https://gitlab.com/o/beta",
                exclude_paths=["vendor/"],
            ),
        ],
        workspace_root=str(tmp_path / "ws"),
    )
    mgr = RepositoryManager(settings)
    mgr.mark_success("alpha", "abc123")
    mgr.mark_failure("beta", "fetch failed")
    return settings, mgr


def test_repo_uri_scheme() -> None:
    assert repo_uri("alpha") == "codesearch://repo/alpha"
    assert repo_uri("a.b-c_d") == "codesearch://repo/a.b-c_d"


async def test_resources_list_advertises_all_configured_repos(tmp_path: Path) -> None:
    settings, mgr = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.list_resources()
        uris = {str(r.uri) for r in result.resources}
        assert uris == {repo_uri("alpha"), repo_uri("beta")}
        # Each entry advertises its id-based name so the LLM sees it in tools listings.
        names = {r.name for r in result.resources}
        assert names == {"Repository: alpha", "Repository: beta"}


async def test_resources_read_returns_repo_status_json(tmp_path: Path) -> None:
    settings, mgr = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        read_result = await client.read_resource(repo_uri("alpha"))
        assert len(read_result.contents) == 1
        block = read_result.contents[0]
        assert block.mimeType == "application/json"
        payload = json.loads(block.text)
        assert payload["id"] == "alpha"
        assert payload["branch"] == "main"
        assert payload["hosting"] == "github"
        assert payload["hosting_base_url"] == "https://github.com/o/alpha"
        assert payload["description"] == "Frontend Vue.js shop app. Pages under src/views/."
        assert payload["status"]["state"] == "ready"
        assert payload["status"]["last_commit"] == "abc123"
        assert payload["status"]["last_outcome"] == "success"


async def test_resources_read_reports_failed_state(tmp_path: Path) -> None:
    settings, mgr = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        read_result = await client.read_resource(repo_uri("beta"))
        payload = json.loads(read_result.contents[0].text)
        assert payload["branch"] == "develop"
        assert payload["exclude_paths"] == ["vendor/"]
        # description was not set in config → returned as null
        assert payload["description"] is None
        assert payload["status"]["last_outcome"] == "failure"
        assert payload["status"]["last_error"] == "fetch failed"


async def test_resources_list_exposes_operator_description(tmp_path: Path) -> None:
    """The Resource's `description` field (visible in resources/list) should
    surface the operator-supplied repo description so the LLM can use it for
    selection without first calling resources/read."""
    settings, mgr = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.list_resources()
        by_uri = {str(r.uri): r for r in result.resources}
        # alpha has a description → it must be in the Resource.description field.
        assert "Frontend Vue.js shop app" in by_uri[repo_uri("alpha")].description
        # beta has no description → fallback wording is used instead.
        assert "Configured Git repository" in by_uri[repo_uri("beta")].description


async def test_list_repositories_tool_returns_description(tmp_path: Path) -> None:
    settings, mgr = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        res = await client.call_tool("list_repositories", {})
        payload = res.structuredContent or json.loads(res.content[0].text)
        by_id = {r["id"]: r for r in payload["repositories"]}
        assert by_id["alpha"]["description"] == "Frontend Vue.js shop app. Pages under src/views/."
        assert by_id["beta"]["description"] is None


async def test_unknown_resource_uri_returns_mcp_error(tmp_path: Path) -> None:
    """Spec §4.6.5: unknown URIs surface as an MCP protocol-level error
    (`McpError`), not as the tool-side `{code,message,details}` envelope."""
    from mcp.shared.exceptions import McpError

    settings, mgr = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        with pytest.raises(McpError) as ei:
            await client.read_resource("codesearch://repo/does-not-exist")
        assert "Unknown resource" in str(ei.value)


async def test_capabilities_advertise_resources_and_tools(tmp_path: Path) -> None:
    settings, mgr = _settings(tmp_path)
    server = build_server(settings, mgr)
    async with create_connected_server_and_client_session(server) as client:
        init = await client.initialize()
        assert init.capabilities.tools is not None
        assert init.capabilities.resources is not None
        # prompts は引き続き未公開ではないが、FastMCP の現実装ではハンドラ登録
        # の都合で空オブジェクトが出る。spec 整合の観点では tools/resources
        # が立っていれば本タスクの要件を満たす。
        assert init.serverInfo.name == "codesearch-mcp"
