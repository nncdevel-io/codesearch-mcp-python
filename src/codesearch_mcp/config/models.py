"""Pydantic models for repos.toml and secrets.toml (spec §7)."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..giturl import Hosting

REPO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


class AuthType(StrEnum):
    TOKEN = "token"  # noqa: S105 - enum label, not a secret
    SSH_KEY = "ssh_key"
    NONE = "none"


class Transport(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


class ServerConfig(BaseModel):
    """Runtime settings for the `serve` subcommand.

    Loaded from ``config/server.toml`` (auto-discovered) and overlaid by CLI
    flags. Repository / secret paths live elsewhere (see :class:`Settings`)
    because they share a different lifecycle.
    """

    model_config = ConfigDict(extra="forbid")

    transport: Transport = Transport.STDIO
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    enable_scheduler: bool = False

    def overlay_cli(
        self,
        *,
        transport: str | Transport | None,
        host: str | None,
        port: int | None,
        enable_scheduler: bool | None,
    ) -> ServerConfig:
        """Return a copy with non-None CLI values applied as overrides."""
        return ServerConfig(
            transport=transport if transport is not None else self.transport,
            host=host if host is not None else self.host,
            port=port if port is not None else self.port,
            enable_scheduler=(
                enable_scheduler if enable_scheduler is not None else self.enable_scheduler
            ),
        )


class RepositoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    remote: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    hosting: Hosting
    hosting_base_url: str = Field(min_length=1)
    refresh_interval_seconds: int = Field(default=900, ge=60)
    exclude_paths: list[str] = Field(default_factory=list)
    # Free-form text describing what this repository contains. Intended use:
    # paste an AI-generated summary so the LLM can pick the right repository
    # for a query without guessing from the id. See docs/operations.md.
    description: str | None = Field(default=None, max_length=8192)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not REPO_ID_PATTERN.fullmatch(v):
            raise ValueError("repository id must match ^[a-zA-Z0-9._-]+$")
        return v

    @field_validator("exclude_paths")
    @classmethod
    def _validate_exclude_paths(cls, v: list[str]) -> list[str]:
        for p in v:
            if not p:
                raise ValueError("exclude_paths entries must be non-empty")
            if p.startswith("/"):
                raise ValueError("exclude_paths entries must be relative")
            if ".." in p.split("/"):
                raise ValueError("exclude_paths must not contain ..")
        return v


class SecretConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auth_type: AuthType
    token: str | None = None
    ssh_key_path: str | None = None

    @model_validator(mode="after")
    def _validate_auth_fields(self) -> SecretConfig:
        if self.auth_type is AuthType.TOKEN and not self.token:
            raise ValueError("token is required when auth_type=token")
        if self.auth_type is AuthType.SSH_KEY and not self.ssh_key_path:
            raise ValueError("ssh_key_path is required when auth_type=ssh_key")
        if self.auth_type is AuthType.NONE and (self.token or self.ssh_key_path):
            raise ValueError("token/ssh_key_path must be unset when auth_type=none")
        return self


class RepositoriesFile(BaseModel):
    """Top-level shape of ``config/repos.toml``.

    Carries the repository catalog plus *optional* paths that share the
    catalog's lifecycle (where clones live, where the matching secrets file
    lives). These optional paths are file-level defaults; CLI args and env
    vars override them.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_root: str | None = None
    secrets: str | None = None
    repository: list[RepositoryConfig] = Field(default_factory=list)


class Settings(BaseModel):
    """Aggregate of repo + secret config plus workspace layout."""

    model_config = ConfigDict(extra="forbid")

    repositories: list[RepositoryConfig]
    secrets: dict[str, SecretConfig] = Field(default_factory=dict)
    workspace_root: str = Field(default="./workspaces")

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> Settings:
        seen: set[str] = set()
        for r in self.repositories:
            if r.id in seen:
                raise ValueError(f"duplicate repository id: {r.id}")
            seen.add(r.id)
        return self

    def orphan_secret_ids(self) -> list[str]:
        """Secret entries whose key does not match any repository id.

        Not fatal — secrets are optional (repos without an entry default to
        ``auth_type=none``), so an orphan is usually a stale leftover. The
        loader logs these as a warning at startup.
        """
        ids = {r.id for r in self.repositories}
        return [sid for sid in self.secrets if sid not in ids]

    def secret_for(self, repo_id: str) -> SecretConfig:
        return self.secrets.get(repo_id, SecretConfig(auth_type=AuthType.NONE))
