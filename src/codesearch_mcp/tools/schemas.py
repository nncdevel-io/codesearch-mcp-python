"""Pydantic input schemas for the four MCP tools and a shared ToolContext."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config.models import Settings
from ..repo.manager import RepositoryManager

_REPO_ID = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_repo_id(v: str) -> str:
    if not _REPO_ID.fullmatch(v):
        raise ValueError("repository must match ^[a-zA-Z0-9._-]+$")
    return v


class SearchCodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1, max_length=1024)
    repository: str = Field(min_length=1, max_length=64)
    path: str | None = Field(default=None, max_length=4096)
    glob: str | None = Field(default=None, max_length=256)
    type: str | None = Field(default=None, max_length=64)
    case_sensitive: bool = False
    output_mode: Literal["content", "files_with_matches", "count"] = "content"
    context_before: int = Field(default=0, ge=0, le=20)
    context_after: int = Field(default=0, ge=0, le=20)
    max_results: int = Field(default=50, ge=1, le=500)

    @field_validator("repository")
    @classmethod
    def _repo(cls, v: str) -> str:
        return _validate_repo_id(v)


class ListFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=64)
    pattern: str = Field(min_length=1, max_length=256)
    path: str | None = Field(default=None, max_length=4096)
    max_results: int = Field(default=100, ge=1, le=500)

    @field_validator("repository")
    @classmethod
    def _repo(cls, v: str) -> str:
        return _validate_repo_id(v)


class ListTreeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=64)
    path: str | None = Field(default=None, max_length=4096)
    max_depth: int = Field(default=2, ge=1, le=5)
    show_files: bool = True
    max_entries: int = Field(default=200, ge=1, le=1000)

    @field_validator("repository")
    @classmethod
    def _repo(cls, v: str) -> str:
        return _validate_repo_id(v)


class ListRepositoriesInput(BaseModel):
    """`list_repositories` takes no arguments; explicit empty schema keeps the
    spec/impl alignment test happy."""

    model_config = ConfigDict(extra="forbid")


class ReadFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=64)
    file_path: str = Field(min_length=1, max_length=4096)
    start_line: int = Field(default=1, ge=1)
    num_lines: int = Field(default=100, ge=1, le=2000)

    @field_validator("repository")
    @classmethod
    def _repo(cls, v: str) -> str:
        return _validate_repo_id(v)


@dataclass(slots=True)
class ToolContext:
    """Shared dependency container passed to every tool call."""

    settings: Settings
    manager: RepositoryManager
