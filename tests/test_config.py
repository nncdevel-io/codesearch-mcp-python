"""Tests for the config models and loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codesearch_mcp.config.loader import (
    ConfigError,
    load_repos,
    load_repositories_file,
    load_secrets,
    load_settings,
    resolve_repos_path,
    resolve_secrets_path,
    resolve_workspace_root,
)
from codesearch_mcp.config.models import AuthType, RepositoryConfig, SecretConfig
from codesearch_mcp.giturl import Hosting

REPOS_FIXTURE = """
[[repository]]
id = "a"
remote = "x"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/a"
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SEARCH_REPOS_PATH", raising=False)
    monkeypatch.delenv("CODE_SEARCH_SECRETS_PATH", raising=False)
    monkeypatch.delenv("CODE_SEARCH_WORKSPACE_ROOT", raising=False)


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


def test_repos_file_carries_optional_top_level_paths(tmp_path: Path) -> None:
    p = tmp_path / "repos.toml"
    _write(
        p,
        """
workspace_root = "/var/lib/codesearch/work"
secrets = "/etc/codesearch/secrets.toml"

[[repository]]
id = "a"
remote = "x"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/a"
""",
    )
    file = load_repositories_file(p)
    assert file.workspace_root == "/var/lib/codesearch/work"
    assert file.secrets == "/etc/codesearch/secrets.toml"
    assert [r.id for r in file.repository] == ["a"]


def test_load_settings_unique_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
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
        load_settings(repos_arg=str(p), secrets_arg=None, workspace_arg=None)


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


def test_resolve_repos_cli_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODE_SEARCH_REPOS_PATH", "/from/env.toml")
    assert resolve_repos_path("/from/cli.toml") == Path("/from/cli.toml")


def test_resolve_repos_env_when_no_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODE_SEARCH_REPOS_PATH", "/from/env.toml")
    assert resolve_repos_path(None) == Path("/from/env.toml")


def test_resolve_repos_auto_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "repos.toml").write_text("# placeholder\n")
    assert resolve_repos_path(None) == Path("config/repos.toml")


def test_resolve_repos_errors_when_nothing_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    with pytest.raises(ConfigError):
        resolve_repos_path(None)


def test_resolve_secrets_precedence_cli_over_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    assert resolve_secrets_path("/cli.toml", "/from-file.toml") == Path("/cli.toml")


def test_resolve_secrets_file_when_no_cli_or_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    assert resolve_secrets_path(None, "/from-file.toml") == Path("/from-file.toml")


def test_resolve_secrets_returns_none_when_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    assert resolve_secrets_path(None, None) is None


def test_resolve_workspace_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    # CLI wins
    assert resolve_workspace_root("/cli/ws", "/file/ws") == Path("/cli/ws")
    # File wins when no CLI/env
    assert resolve_workspace_root(None, "/file/ws") == Path("/file/ws")
    # Built-in default when nothing
    assert resolve_workspace_root(None, None) == Path("./workspaces")


def test_load_settings_uses_repos_toml_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File-level workspace_root takes effect when no CLI/env override is set."""
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    p = tmp_path / "config" / "repos.toml"
    _write(
        p,
        """
workspace_root = "/from/repos-toml/ws"

[[repository]]
id = "a"
remote = "x"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/a"
""",
    )
    settings = load_settings(repos_arg=None, secrets_arg=None, workspace_arg=None)
    assert settings.workspace_root == "/from/repos-toml/ws"


def test_load_settings_cli_overrides_repos_toml_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    p = tmp_path / "repos.toml"
    _write(
        p,
        """
workspace_root = "/from/repos-toml/ws"

[[repository]]
id = "a"
remote = "x"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/a"
""",
    )
    settings = load_settings(repos_arg=str(p), secrets_arg=None, workspace_arg="/cli/ws")
    assert settings.workspace_root == "/cli/ws"


def test_load_settings_warns_on_orphan_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Orphan secret entries log a warning but do not block startup."""
    import logging

    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    repos = tmp_path / "repos.toml"
    secrets = tmp_path / "secrets.toml"
    _write(repos, REPOS_FIXTURE)
    _write(
        secrets,
        """
[secrets.unknown]
auth_type = "none"
""",
    )
    os.chmod(secrets, 0o600)
    with caplog.at_level(logging.WARNING):
        settings = load_settings(repos_arg=str(repos), secrets_arg=str(secrets), workspace_arg=None)
    assert settings.orphan_secret_ids() == ["unknown"]
    # log_event stores the structured payload on the record's `ctx` extra.
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any(getattr(rec, "ctx", {}).get("reason") == "orphan_secret_entries" for rec in warnings)


@pytest.mark.parametrize(
    ("exclude_paths", "expected_message"),
    [
        ([""], "must be non-empty"),
        (["/abs/path"], "must be relative"),
        (["a/../b"], "must not contain .."),
    ],
)
def test_repository_exclude_paths_validation(
    exclude_paths: list[str], expected_message: str
) -> None:
    """``RepositoryConfig._validate_exclude_paths`` enforces non-empty, relative,
    and traversal-free entries (lines 86-91)."""
    with pytest.raises(Exception) as ei:
        RepositoryConfig(
            id="ok",
            remote="x",
            branch="main",
            hosting=Hosting.GITHUB,
            hosting_base_url="https://example.com",
            exclude_paths=exclude_paths,
        )
    assert expected_message in str(ei.value)


def test_secret_none_must_not_have_credentials() -> None:
    """``SecretConfig._validate_auth_fields`` rejects ``auth_type=none`` paired
    with token/ssh_key_path (line 109)."""
    with pytest.raises(Exception) as ei:
        SecretConfig(auth_type=AuthType.NONE, token="leftover")
    assert "must be unset when auth_type=none" in str(ei.value)
    with pytest.raises(Exception) as ei:
        SecretConfig(auth_type=AuthType.NONE, ssh_key_path="/leftover")
    assert "must be unset when auth_type=none" in str(ei.value)


def test_read_toml_wraps_os_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When reading the TOML file raises ``OSError``, ``_read_toml`` re-wraps it
    as ``ConfigError`` (lines 36-37)."""
    p = tmp_path / "repos.toml"
    _write(p, REPOS_FIXTURE)

    def _boom(self: Path) -> bytes:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", _boom)
    with pytest.raises(ConfigError) as ei:
        load_repos(p)
    assert "failed to read config file" in str(ei.value)


def test_load_repositories_file_rejects_invalid_schema(tmp_path: Path) -> None:
    """Repos TOML that parses but fails Pydantic validation raises
    ``ConfigError`` (lines 52-53)."""
    p = tmp_path / "repos.toml"
    # ``hosting`` is required but missing → Pydantic ValidationError.
    _write(
        p,
        """
[[repository]]
id = "a"
remote = "x"
branch = "main"
""",
    )
    with pytest.raises(ConfigError) as ei:
        load_repositories_file(p)
    assert "invalid repos.toml" in str(ei.value)


def test_check_secret_permissions_wraps_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``Path.stat()`` raises ``OSError`` on the secrets file,
    ``_check_secret_permissions`` re-wraps as ``ConfigError`` (lines 67-68)."""
    p = tmp_path / "secrets.toml"
    _write(p, '[secrets.a]\nauth_type = "none"\n')
    os.chmod(p, 0o600)

    original_stat = Path.stat

    def _boom(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self == p:
            raise PermissionError("denied")
        return original_stat(self, *args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr(Path, "stat", _boom)
    with pytest.raises(ConfigError) as ei:
        load_secrets(p)
    assert "failed to stat secrets file" in str(ei.value)


def test_load_secrets_rejects_non_table_secrets_section(tmp_path: Path) -> None:
    """``[secrets]`` must be a TOML table, not a scalar or array (line 84)."""
    p = tmp_path / "secrets.toml"
    _write(p, 'secrets = "not-a-table"\n')
    os.chmod(p, 0o600)
    with pytest.raises(ConfigError) as ei:
        load_secrets(p)
    assert "[secrets] section must be a table" in str(ei.value)


def test_load_secrets_rejects_invalid_entry(tmp_path: Path) -> None:
    """A malformed ``[secrets.<id>]`` entry raises ``ConfigError`` referencing
    the offending id (lines 89-90)."""
    p = tmp_path / "secrets.toml"
    _write(
        p,
        """
[secrets.bad]
auth_type = "token"
""",  # token auth without token field
    )
    os.chmod(p, 0o600)
    with pytest.raises(ConfigError) as ei:
        load_secrets(p)
    assert "invalid [secrets.bad]" in str(ei.value)


def test_resolve_secrets_auto_discovery_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no CLI/env/file value is set and ``./config/secrets.toml`` exists,
    ``resolve_secrets_path`` returns that default (line 122)."""
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    (tmp_path / "config").mkdir()
    secrets = tmp_path / "config" / "secrets.toml"
    secrets.write_text("# placeholder\n")
    assert resolve_secrets_path(None, None) == Path("config/secrets.toml")


def test_load_settings_no_warning_when_all_descriptions_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Two repos both with descriptions → ``_warn_on_missing_descriptions``
    falls through without logging (branch 193→exit)."""
    import logging

    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    p = tmp_path / "repos.toml"
    _write(
        p,
        """
[[repository]]
id = "a"
remote = "x"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/a"
description = "alpha"

[[repository]]
id = "b"
remote = "y"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/b"
description = "beta"
""",
    )
    with caplog.at_level(logging.WARNING):
        load_settings(repos_arg=str(p), secrets_arg=None, workspace_arg=None)
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert not any(
        getattr(rec, "ctx", {}).get("reason") == "repositories_without_description"
        for rec in warnings
    )


def test_load_settings_warns_on_missing_descriptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """With 2+ repos and any missing ``description``, ``_warn_on_missing_descriptions``
    logs a structured warning (lines 192-194)."""
    import logging

    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    p = tmp_path / "repos.toml"
    _write(
        p,
        """
[[repository]]
id = "a"
remote = "x"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/a"

[[repository]]
id = "b"
remote = "y"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/o/b"
""",
    )
    with caplog.at_level(logging.WARNING):
        load_settings(repos_arg=str(p), secrets_arg=None, workspace_arg=None)
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any(
        getattr(rec, "ctx", {}).get("reason") == "repositories_without_description"
        for rec in warnings
    )
