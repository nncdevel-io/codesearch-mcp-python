"""Tests for the config models and loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codesearch_mcp.config.loader import (
    ConfigError,
    load_repos,
    load_secrets,
    load_settings,
)
from codesearch_mcp.config.models import AuthType, RepositoryConfig, SecretConfig
from codesearch_mcp.giturl import Hosting


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_repository_minimum_valid() -> None:
    r = RepositoryConfig(
        id="main-app",
        remote="git@github.com:example/main-app.git",
        branch="main",
        hosting=Hosting.GITHUB,
        hosting_base_url="https://github.com/example/main-app",
    )
    assert r.refresh_interval_seconds == 900
    assert r.exclude_paths == []
    # description is optional and defaults to None
    assert r.description is None


def test_repository_accepts_long_description() -> None:
    long_text = (
        "Backend service for billing. Implements Stripe integration, "
        "invoice generation, and webhook ingestion. Built with FastAPI + "
        "SQLAlchemy. Key modules: billing/, webhooks/, models/."
    )
    r = RepositoryConfig(
        id="billing-svc",
        remote="git@example.com:billing-svc.git",
        branch="main",
        hosting=Hosting.GITHUB,
        hosting_base_url="https://github.com/example/billing-svc",
        description=long_text,
    )
    assert r.description == long_text


def test_repository_description_length_capped() -> None:
    with pytest.raises(Exception):
        RepositoryConfig(
            id="x",
            remote="x",
            branch="main",
            hosting=Hosting.GITHUB,
            hosting_base_url="https://example.com",
            description="x" * 8193,
        )


def test_repository_id_must_match_pattern() -> None:
    with pytest.raises(Exception):
        RepositoryConfig(
            id="bad id",
            remote="x",
            branch="main",
            hosting=Hosting.GITHUB,
            hosting_base_url="https://example.com",
        )


def test_repository_hosting_enum_validated() -> None:
    with pytest.raises(Exception):
        RepositoryConfig(
            id="ok",
            remote="x",
            branch="main",
            hosting="mercurial",  # type: ignore[arg-type]
            hosting_base_url="https://example.com",
        )


def test_repository_refresh_minimum() -> None:
    with pytest.raises(Exception):
        RepositoryConfig(
            id="ok",
            remote="x",
            branch="main",
            hosting=Hosting.GITHUB,
            hosting_base_url="https://example.com",
            refresh_interval_seconds=30,
        )


def test_secret_token_requires_token() -> None:
    with pytest.raises(Exception):
        SecretConfig(auth_type=AuthType.TOKEN)


def test_secret_ssh_requires_path() -> None:
    with pytest.raises(Exception):
        SecretConfig(auth_type=AuthType.SSH_KEY)


def test_load_repos_happy_path(tmp_path: Path) -> None:
    p = tmp_path / "repos.toml"
    _write(
        p,
        """
[[repository]]
id = "a"
remote = "git@github.com:o/a.git"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/a"

[[repository]]
id = "b"
remote = "git@github.com:o/b.git"
branch = "main"
hosting = "gitlab"
hosting_base_url = "https://gitlab.com/o/b"
refresh_interval_seconds = 120
exclude_paths = ["vendor/", "build/"]
""",
    )
    repos = load_repos(p)
    assert [r.id for r in repos] == ["a", "b"]
    assert repos[1].refresh_interval_seconds == 120
    assert repos[1].exclude_paths == ["vendor/", "build/"]


def test_load_repos_rejects_empty(tmp_path: Path) -> None:
    p = tmp_path / "repos.toml"
    _write(p, "")
    with pytest.raises(ConfigError):
        load_repos(p)


def test_load_repos_rejects_bad_toml(tmp_path: Path) -> None:
    p = tmp_path / "repos.toml"
    _write(p, "this is not toml = [")
    with pytest.raises(ConfigError):
        load_repos(p)


def test_load_settings_unique_ids(tmp_path: Path) -> None:
    p = tmp_path / "repos.toml"
    _write(
        p,
        """
[[repository]]
id = "dup"
remote = "x"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/dup"

[[repository]]
id = "dup"
remote = "y"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/dup2"
""",
    )
    with pytest.raises(ConfigError):
        load_settings(p, None, tmp_path / "ws")


def test_load_secrets_requires_strict_permissions(tmp_path: Path) -> None:
    p = tmp_path / "secrets.toml"
    _write(
        p,
        """
[secrets.a]
auth_type = "token"
token = "x"
""",
    )
    os.chmod(p, 0o644)
    with pytest.raises(ConfigError):
        load_secrets(p)


def test_load_secrets_accepts_600(tmp_path: Path) -> None:
    p = tmp_path / "secrets.toml"
    _write(
        p,
        """
[secrets.a]
auth_type = "token"
token = "tok"
""",
    )
    os.chmod(p, 0o600)
    secrets = load_secrets(p)
    assert secrets["a"].auth_type is AuthType.TOKEN


def test_load_secrets_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_secrets(tmp_path / "absent.toml") == {}


def test_load_settings_rejects_secret_for_unknown_repo(tmp_path: Path) -> None:
    repos = tmp_path / "repos.toml"
    secrets = tmp_path / "secrets.toml"
    _write(
        repos,
        """
[[repository]]
id = "a"
remote = "x"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/a"
""",
    )
    _write(
        secrets,
        """
[secrets.unknown]
auth_type = "none"
""",
    )
    os.chmod(secrets, 0o600)
    with pytest.raises(ConfigError):
        load_settings(repos, secrets, tmp_path / "ws")
