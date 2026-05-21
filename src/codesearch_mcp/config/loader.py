"""Loader and startup validation for repos.toml / secrets.toml (spec §7.3)."""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..logging import log_event
from .models import (
    AuthType,
    RepositoriesFile,
    RepositoryConfig,
    SecretConfig,
    ServerConfig,
    Settings,
)

DEFAULT_REPOS_PATH = Path("./config/repos.toml")
DEFAULT_SECRETS_PATH = Path("./config/secrets.toml")
DEFAULT_WORKSPACE_ROOT = Path("./workspaces")
DEFAULT_SERVER_CONFIG_PATH = Path("./config/server.toml")


class ConfigError(Exception):
    """Raised on configuration parse or validation failure (server start aborts)."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"failed to read config file: {path}: {exc}") from exc
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"failed to parse TOML: {path}: {exc}") from exc


def load_repositories_file(path: Path) -> RepositoriesFile:
    """Parse a ``repos.toml`` into the top-level :class:`RepositoriesFile`.

    Validates that at least one ``[[repository]]`` entry is present.
    """
    parsed = _read_toml(path)
    try:
        file = RepositoriesFile.model_validate(parsed)
    except ValidationError as exc:
        raise ConfigError(f"{path}: invalid repos.toml: {exc}") from exc
    if not file.repository:
        raise ConfigError(f"{path}: at least one [[repository]] entry is required")
    return file


def load_repos(path: Path) -> list[RepositoryConfig]:
    """Backward-compatible helper returning only the repository list."""
    return load_repositories_file(path).repository


def _check_secret_permissions(path: Path) -> None:
    try:
        st = path.stat()
    except OSError as exc:
        raise ConfigError(f"failed to stat secrets file: {path}: {exc}") from exc
    mode = stat.S_IMODE(st.st_mode)
    forbidden = stat.S_IRWXG | stat.S_IRWXO
    if mode & forbidden:
        raise ConfigError(
            f"{path}: secrets file permissions must be 600 or stricter (got {oct(mode)})"
        )


def load_secrets(path: Path | None) -> dict[str, SecretConfig]:
    if path is None or not path.exists():
        return {}
    _check_secret_permissions(path)
    parsed = _read_toml(path)
    raw = parsed.get("secrets", {})
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [secrets] section must be a table")
    secrets: dict[str, SecretConfig] = {}
    for sid, entry in raw.items():
        try:
            secrets[sid] = SecretConfig.model_validate(entry)
        except ValidationError as exc:
            raise ConfigError(f"{path}: invalid [secrets.{sid}]: {exc}") from exc
    return secrets


def resolve_repos_path(repos_arg: str | None) -> Path:
    """Resolve repos.toml path: CLI > env > auto-discovery.

    Errors out if no candidate exists, since the catalog is required for
    every subcommand.
    """
    explicit = repos_arg or os.environ.get("CODE_SEARCH_REPOS_PATH")
    if explicit:
        return Path(explicit)
    if DEFAULT_REPOS_PATH.exists():
        return DEFAULT_REPOS_PATH
    raise ConfigError(
        "repos config path is required (use --repos, CODE_SEARCH_REPOS_PATH, "
        f"or place {DEFAULT_REPOS_PATH})"
    )


def resolve_secrets_path(secrets_arg: str | None, file_value: str | None) -> Path | None:
    """Resolve secrets.toml path: CLI > env > repos.toml file value > auto-discovery.

    Returns ``None`` when no candidate file exists (secrets are optional).
    """
    explicit = secrets_arg or os.environ.get("CODE_SEARCH_SECRETS_PATH")
    if explicit:
        return Path(explicit)
    if file_value:
        return Path(file_value)
    if DEFAULT_SECRETS_PATH.exists():
        return DEFAULT_SECRETS_PATH
    return None


def resolve_workspace_root(workspace_arg: str | None, file_value: str | None) -> Path:
    """Resolve workspace root: CLI > env > repos.toml file value > built-in default."""
    explicit = workspace_arg or os.environ.get("CODE_SEARCH_WORKSPACE_ROOT")
    if explicit:
        return Path(explicit)
    if file_value:
        return Path(file_value)
    return DEFAULT_WORKSPACE_ROOT


def load_settings(
    *,
    repos_arg: str | None,
    secrets_arg: str | None,
    workspace_arg: str | None,
) -> Settings:
    """End-to-end: locate repos.toml, load it, resolve sibling paths, validate.

    Path precedence is **CLI > env > repos.toml > built-in default** (the
    auto-discovery default applies to repos and secrets file locations).
    """
    repos_path = resolve_repos_path(repos_arg)
    repos_file = load_repositories_file(repos_path)
    secrets_path = resolve_secrets_path(secrets_arg, repos_file.secrets)
    workspace = resolve_workspace_root(workspace_arg, repos_file.workspace_root)
    secrets = load_secrets(secrets_path)
    try:
        settings = Settings(
            repositories=repos_file.repository,
            secrets=secrets,
            workspace_root=str(workspace),
        )
    except ValidationError as exc:
        raise ConfigError(f"configuration validation failed: {exc}") from exc

    _warn_on_missing_descriptions(settings)
    _warn_on_orphan_secrets(settings)
    return settings


def _warn_on_orphan_secrets(settings: Settings) -> None:
    """Log a warning for secret entries that don't match any repository id."""
    orphans = settings.orphan_secret_ids()
    if orphans:
        log_event(
            "warning",
            "config_warning",
            reason="orphan_secret_entries",
            orphan_secret_ids=orphans,
            advice=(
                "Remove unused [secrets.<id>] entries or correct the id to match "
                "a repository. Orphan entries are ignored at runtime."
            ),
        )


def _warn_on_missing_descriptions(settings: Settings) -> None:
    """Emit a config_warning when multiple repos lack a `description`.

    The LLM relies on per-repo descriptions to pick the right `repository`
    argument. With 2+ repos and none/some missing descriptions, the LLM has
    to guess. See docs/operations.md "リポジトリ description の運用".
    """

    if len(settings.repositories) < 2:
        return
    missing = [r.id for r in settings.repositories if not r.description]
    if missing:
        log_event(
            "warning",
            "config_warning",
            reason="repositories_without_description",
            repositories=missing,
            advice=(
                "Set `description` in repos.toml for each repository so the "
                "LLM can choose the right one. See docs/operations.md."
            ),
        )


def load_server_config(path: Path, *, required: bool = False) -> ServerConfig:
    """Load server-runtime settings from a TOML file.

    Returns built-in defaults if the file is missing and ``required`` is
    False. Raises :class:`ConfigError` when an explicitly-requested path
    does not exist (``required=True``) or when the file is invalid.
    """
    if not path.exists():
        if required:
            raise ConfigError(f"server config file not found: {path}")
        return ServerConfig()
    parsed = _read_toml(path)
    try:
        return ServerConfig.model_validate(parsed)
    except ValidationError as exc:
        raise ConfigError(f"{path}: invalid server config: {exc}") from exc


def discover_server_config_path(cli_arg: str | None) -> tuple[Path, bool]:
    """Resolve the server config path.

    Returns ``(path, explicit)`` where ``explicit`` is True when the path
    came from ``--config`` or the ``CODE_SEARCH_CONFIG_PATH`` env var. The
    auto-discovered default (``./config/server.toml``) returns False — the
    caller treats a missing default as "use built-in defaults".
    """
    explicit = cli_arg or os.environ.get("CODE_SEARCH_CONFIG_PATH")
    if explicit:
        return Path(explicit), True
    return DEFAULT_SERVER_CONFIG_PATH, False


__all__ = [
    "AuthType",
    "ConfigError",
    "DEFAULT_REPOS_PATH",
    "DEFAULT_SECRETS_PATH",
    "DEFAULT_SERVER_CONFIG_PATH",
    "DEFAULT_WORKSPACE_ROOT",
    "discover_server_config_path",
    "load_repos",
    "load_repositories_file",
    "load_secrets",
    "load_server_config",
    "load_settings",
    "resolve_repos_path",
    "resolve_secrets_path",
    "resolve_workspace_root",
]
