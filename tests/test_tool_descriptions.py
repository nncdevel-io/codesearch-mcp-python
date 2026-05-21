"""Regression checks for the LLM-facing copy advertised via capability discovery.

The strings the LLM uses to decide *whether* and *which* tool to call live in
``codesearch_mcp.llm_guidance``. Three things must stay aligned:

1. The constants in ``llm_guidance.py`` themselves contain certain key phrases
   (so we cannot silently drop e.g. the "list_tree FIRST" advice).
2. The FastMCP server actually advertises those constants via the MCP
   ``initialize`` and ``tools/list`` responses (regression against accidental
   reverts to the old one-line descriptions).
3. ``docs/usage-for-llm.md`` mirrors the same constants (catches doc drift).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codesearch_mcp.config.models import RepositoryConfig, Settings
from codesearch_mcp.giturl import Hosting
from codesearch_mcp.llm_guidance import (
    LIST_FILES_DESCRIPTION,
    LIST_REPOSITORIES_DESCRIPTION,
    LIST_TREE_DESCRIPTION,
    READ_FILE_DESCRIPTION,
    SEARCH_CODE_DESCRIPTION,
    SERVER_INSTRUCTIONS,
)
from codesearch_mcp.repo.manager import RepositoryManager
from codesearch_mcp.server import build_server

USAGE_DOC = Path(__file__).resolve().parent.parent / "docs" / "usage-for-llm.md"


def _build_minimal_server():
    settings = Settings(
        repositories=[
            RepositoryConfig(
                id="probe",
                remote="x",
                branch="main",
                hosting=Hosting.GITHUB,
                hosting_base_url="https://github.com/o/probe",
            )
        ],
        workspace_root="/tmp/never-used",
    )
    return build_server(settings, RepositoryManager(settings))


# ---- (1) constants carry the key phrases ----------------------------------


def test_server_instructions_describes_workflow_order() -> None:
    text = SERVER_INSTRUCTIONS
    # Workflow order is the load-bearing piece of advice.
    for token in ("list_tree", "search_code", "read_file", "list_files"):
        assert token in text, f"server instructions must mention {token}"
    # And it must say what we DO NOT do, so the LLM doesn't ask us for it.
    assert "NOT do" in text or "does NOT" in text
    assert "vector" in text.lower()
    assert "git_url" in text
    # The repository catalog is discovered via the Resources surface — the
    # instructions must tell the LLM that.
    assert "resources/list" in text
    assert "codesearch://repo" in text


@pytest.mark.parametrize(
    "name,text,must_contain",
    [
        (
            "search_code",
            SEARCH_CODE_DESCRIPTION,
            ["regular expression", "output_mode", "files_with_matches", "max_results"],
        ),
        (
            "list_files",
            LIST_FILES_DESCRIPTION,
            ["filename", "last_modified", "search_code"],
        ),
        (
            "list_tree",
            LIST_TREE_DESCRIPTION,
            ["FIRST", "tracked", "max_depth", "max_entries"],
        ),
        (
            "read_file",
            READ_FILE_DESCRIPTION,
            ["line range", "FILE_TOO_LARGE", "FILE_BINARY", "git_url"],
        ),
        (
            "list_repositories",
            LIST_REPOSITORIES_DESCRIPTION,
            ["catalog", "resources/list", "FIRST", "takes no arguments"],
        ),
    ],
)
def test_tool_description_carries_key_phrases(
    name: str, text: str, must_contain: list[str]
) -> None:
    for token in must_contain:
        assert token in text, f"{name} description must mention {token!r}"


# ---- (2) FastMCP actually advertises those constants ----------------------


def test_fastmcp_publishes_server_instructions() -> None:
    server = _build_minimal_server()
    # FastMCP stores instructions on the underlying low-level server.
    assert server.instructions == SERVER_INSTRUCTIONS


def test_fastmcp_publishes_full_tool_descriptions() -> None:
    server = _build_minimal_server()
    by_name = {t.name: t for t in server._tool_manager.list_tools()}
    assert by_name["search_code"].description == SEARCH_CODE_DESCRIPTION
    assert by_name["list_files"].description == LIST_FILES_DESCRIPTION
    assert by_name["list_tree"].description == LIST_TREE_DESCRIPTION
    assert by_name["read_file"].description == READ_FILE_DESCRIPTION
    assert by_name["list_repositories"].description == LIST_REPOSITORIES_DESCRIPTION


# ---- (3) docs/usage-for-llm.md mirrors the same text ----------------------


@pytest.mark.parametrize(
    "snippet",
    [
        SERVER_INSTRUCTIONS,
        SEARCH_CODE_DESCRIPTION,
        LIST_FILES_DESCRIPTION,
        LIST_TREE_DESCRIPTION,
        READ_FILE_DESCRIPTION,
        LIST_REPOSITORIES_DESCRIPTION,
    ],
)
def test_usage_doc_mirrors_constants(snippet: str) -> None:
    doc = USAGE_DOC.read_text(encoding="utf-8")
    # Quote-aware: the doc wraps each block in ``` ``` fences, so just check
    # that every non-empty line of the constant appears verbatim.
    for line in snippet.strip().splitlines():
        if line.strip():
            assert line in doc, (
                f"docs/usage-for-llm.md is out of sync with llm_guidance.py: missing line {line!r}"
            )
