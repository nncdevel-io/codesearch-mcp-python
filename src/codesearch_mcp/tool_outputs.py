"""Pydantic output models for the MCP tools.

These mirror the per-tool outputSchema definitions in
``docs/spec/spec.md`` §4.x and are attached to each FastMCP tool so that the
spec is also advertised at runtime via ``tools/list``.

Why this is its own module: each model is a verbatim transcription of the
spec. Keeping them separate makes the spec ↔ impl alignment test
(`test_schema_alignment.py`) straightforward and prevents accidental drift
from the runtime tool functions.

Error responses are NOT validated against these models. They are returned as
``CallToolResult(isError=True, content=[TextContent(text=JSON)])`` with
``structuredContent=None``; the server registration code patches
``FuncMetadata.convert_result`` to skip validation on that shape (spec §5.1
forbids structuredContent on the error path).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- search_code -------------------------------------------------------------


class SearchContextLine(_StrictModel):
    line_number: int
    content: str


class SearchMatch(_StrictModel):
    repository: str
    file_path: str
    line_number: int = Field(ge=1)
    line_content: str
    context_before: list[SearchContextLine] = Field(default_factory=list)
    context_after: list[SearchContextLine] = Field(default_factory=list)
    git_url: str


class SearchContentOutput(_StrictModel):
    """search_code response when output_mode == 'content' (spec §4.1.2)."""

    matches: list[SearchMatch]
    truncated: bool
    total_matches: int = Field(ge=0)


class SearchFileEntry(_StrictModel):
    repository: str
    file_path: str
    git_url: str


class SearchFilesWithMatchesOutput(_StrictModel):
    """search_code response when output_mode == 'files_with_matches' (spec §4.1.3)."""

    files: list[SearchFileEntry]
    truncated: bool


class SearchCountFileEntry(_StrictModel):
    repository: str
    file_path: str
    match_count: int = Field(ge=1)
    git_url: str


class SearchCountOutput(_StrictModel):
    """search_code response when output_mode == 'count' (spec §4.1.4)."""

    files: list[SearchCountFileEntry]
    truncated: bool


class SearchCodeOutput(
    RootModel[SearchContentOutput | SearchFilesWithMatchesOutput | SearchCountOutput]
):
    """Discriminated union covering the three search_code response shapes."""


# --- list_files --------------------------------------------------------------


class ListFilesEntry(_StrictModel):
    repository: str
    file_path: str
    last_modified: str  # ISO 8601 (date-time)
    git_url: str


class ListFilesOutput(_StrictModel):
    """list_files response (spec §4.2.2)."""

    files: list[ListFilesEntry]
    truncated: bool


# --- list_tree ---------------------------------------------------------------


class ListTreeOutput(_StrictModel):
    """list_tree response (spec §4.3.2)."""

    repository: str
    root_path: str
    tree: str
    truncated: bool
    entry_count: int = Field(ge=0)


# --- read_file ---------------------------------------------------------------


class ReadFileOutput(_StrictModel):
    """read_file response (spec §4.4.2)."""

    repository: str
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=0)
    total_lines: int = Field(ge=0)
    content: str
    git_url: str


# --- list_repositories ------------------------------------------------------


class RepoSyncStatus(_StrictModel):
    repository: str
    state: str
    last_outcome: str | None
    last_sync_at: str | None
    last_commit: str | None
    last_error: str | None


class RepoCatalogEntry(_StrictModel):
    id: str
    branch: str
    hosting: str
    hosting_base_url: str
    exclude_paths: list[str]
    refresh_interval_seconds: int
    description: str | None
    status: RepoSyncStatus | None


class ListRepositoriesOutput(_StrictModel):
    """list_repositories response (spec §4.5.2)."""

    repositories: list[RepoCatalogEntry]


# --- registry ----------------------------------------------------------------


TOOL_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "search_code": SearchCodeOutput,
    "list_files": ListFilesOutput,
    "list_tree": ListTreeOutput,
    "read_file": ReadFileOutput,
    "list_repositories": ListRepositoriesOutput,
}


def output_schema_for(tool_name: str) -> dict[str, Any] | None:
    """JSON Schema (draft-07-ish) for the given tool's success response."""

    model = TOOL_OUTPUT_MODELS.get(tool_name)
    if model is None:
        return None
    return model.model_json_schema()
