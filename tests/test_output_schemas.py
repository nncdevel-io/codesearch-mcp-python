"""Regression tests for the per-tool outputSchema advertisement (TASK-066).

Three things to keep aligned:

1. Each Pydantic output model in ``codesearch_mcp.tool_outputs`` matches the
   structure declared in ``docs/spec/spec.md`` §4.x. (Drift detection on the
   contract.)
2. FastMCP actually advertises those schemas via ``tools/list`` so MCP
   clients can validate responses.
3. The class-level patch (``_convert_result_lenient_on_error``) lets our
   error CallToolResult (structuredContent=None) flow through without
   failing validation.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.server import build_server
from codesearch_mcp.tool_outputs import (
    TOOL_OUTPUT_MODELS,
    ListFilesOutput,
    ListRepositoriesOutput,
    ListTreeOutput,
    ReadFileOutput,
    SearchCodeOutput,
    output_schema_for,
)


def _minimal_server(tmp_path: Path):
    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="probe",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/probe",
                description="Smoke test repo.",
            )
        ],
        workspace_root=str(tmp_path / "ws"),
    )
    return build_server(settings, RepositoryManager(settings))


async def test_all_five_tools_publish_output_schema(tmp_path: Path) -> None:
    server = _minimal_server(tmp_path)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        tools = await client.list_tools()
        for t in tools.tools:
            assert t.outputSchema is not None, f"{t.name} must publish outputSchema"
            assert isinstance(t.outputSchema, dict)
            # Schema metadata that Pydantic always emits.
            assert "title" in t.outputSchema


async def test_search_code_schema_is_union(tmp_path: Path) -> None:
    server = _minimal_server(tmp_path)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        # search_code has 3 modes → its output schema is a union over the
        # three response shapes (spec §4.1.2–4.1.4).
        schema = by_name["search_code"].outputSchema
        assert "anyOf" in schema
        assert len(schema["anyOf"]) == 3


async def test_simple_tools_schema_includes_required_keys(tmp_path: Path) -> None:
    """list_files / list_tree / read_file / list_repositories all have a
    single fixed response shape — verify a few load-bearing keys."""
    server = _minimal_server(tmp_path)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}

        assert set(by_name["list_files"].outputSchema["required"]) == {
            "files",
            "truncated",
        }
        assert set(by_name["list_tree"].outputSchema["required"]) == {
            "repository",
            "root_path",
            "tree",
            "truncated",
            "entry_count",
        }
        assert set(by_name["read_file"].outputSchema["required"]) == {
            "repository",
            "file_path",
            "start_line",
            "end_line",
            "total_lines",
            "content",
            "git_url",
        }
        assert set(by_name["list_repositories"].outputSchema["required"]) == {
            "repositories",
        }


async def test_error_path_still_returns_callToolResult(tmp_path: Path) -> None:
    """Even with outputSchema set, an error from a tool (REPO_NOT_FOUND etc.)
    must surface as isError=True without tripping output_model validation."""
    server = _minimal_server(tmp_path)
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool(
            "read_file",
            {"repository": "does-not-exist", "file_path": "a.py"},
        )
        assert result.isError is True
        # The error envelope JSON lives in content[0].text, not in
        # structuredContent.
        body = json.loads(result.content[0].text)
        assert body["code"] == "REPO_NOT_FOUND"
        assert result.structuredContent is None


def test_tool_output_models_match_registered_tools() -> None:
    """Sanity check: every tool we ship has a Pydantic output model."""
    assert set(TOOL_OUTPUT_MODELS) == {
        "search_code",
        "list_files",
        "list_tree",
        "read_file",
        "list_repositories",
    }
    # Schema generation must succeed for each.
    for model in (
        SearchCodeOutput,
        ListFilesOutput,
        ListTreeOutput,
        ReadFileOutput,
        ListRepositoriesOutput,
    ):
        model.model_json_schema()


def test_output_schema_for_returns_schema_for_known_tool() -> None:
    """``output_schema_for`` returns the JSON Schema dict for a registered
    tool name (line 183)."""
    schema = output_schema_for("read_file")
    assert isinstance(schema, dict)
    assert "title" in schema


def test_output_schema_for_returns_none_for_unknown_tool() -> None:
    """An unrecognized tool name yields ``None`` rather than raising
    (lines 181-182)."""
    assert output_schema_for("nonexistent_tool") is None
