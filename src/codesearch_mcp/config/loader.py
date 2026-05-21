"""Loader and startup validation for repos.toml / secrets.toml (spec §7.3)."""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..logging import log_event
from .models import AuthType, RepositoryConfig, SecretConfig, Settings


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


def load_repos(path: Path) -> list[RepositoryConfig]:
    parsed = _read_toml(path)
    raw_list = parsed.get("repository")
    if not isinstance(raw_list, list) or not raw_list:
        raise ConfigError(f"{path}: at least one [[repository]] entry is required")
    repos: list[RepositoryConfig] = []
    for idx, entry in enumerate(raw_list):
        try:
            repos.append(RepositoryConfig.model_validate(entry))
        except ValidationError as exc:
            raise ConfigError(f"{path}: invalid [[repository]][{idx}]: {exc}") from exc
    return repos


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


def load_settings(
    repos_path: Path,
    secrets_path: Path | None,
    workspace_root: Path,
) -> Settings:
    repos = load_repos(repos_path)
    secrets = load_secrets(secrets_path)
    try:
        settings = Settings(
            repositories=repos,
            secrets=secrets,
            workspace_root=str(workspace_root),
        )
    except ValidationError as exc:
        raise ConfigError(f"configuration validation failed: {exc}") from exc

    _warn_on_missing_descriptions(settings)
    return settings


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


def discover_config_paths(
    repos_arg: str | None,
    secrets_arg: str | None,
    workspace_arg: str | None,
) -> tuple[Path, Path | None, Path]:
    repos = repos_arg or os.environ.get("CODE_SEARCH_REPOS_PATH")
    if not repos:
        raise ConfigError("repos config path is required (use --repos or CODE_SEARCH_REPOS_PATH)")
    secrets = secrets_arg or os.environ.get("CODE_SEARCH_SECRETS_PATH")
    workspace = workspace_arg or os.environ.get("CODE_SEARCH_WORKSPACE_ROOT") or "./workspaces"
    return Path(repos), (Path(secrets) if secrets else None), Path(workspace)


__all__ = [
    "AuthType",
    "ConfigError",
    "discover_config_paths",
    "load_repos",
    "load_secrets",
    "load_settings",
]
