"""Tests for the server-runtime config (transport/host/port/scheduler)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesearch_mcp.config.loader import (
    ConfigError,
    discover_server_config_path,
    load_server_config,
)
from codesearch_mcp.config.models import ServerConfig, Transport


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_defaults() -> None:
    cfg = ServerConfig()
    assert cfg.transport is Transport.STDIO
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000
    assert cfg.enable_scheduler is False


def test_transport_enum_validation() -> None:
    with pytest.raises(Exception):
        ServerConfig(transport="ws")  # type: ignore[arg-type]


def test_port_range_validation() -> None:
    with pytest.raises(Exception):
        ServerConfig(port=0)
    with pytest.raises(Exception):
        ServerConfig(port=70000)


def test_rejects_unknown_field() -> None:
    with pytest.raises(Exception):
        ServerConfig(unknown_field=True)  # type: ignore[call-arg]


def test_overlay_cli_overrides_set_fields() -> None:
    cfg = ServerConfig(transport=Transport.HTTP, host="192.0.2.1", port=9000)
    out = cfg.overlay_cli(transport="stdio", host=None, port=None, enable_scheduler=True)
    assert out.transport is Transport.STDIO  # CLI override
    assert out.host == "192.0.2.1"  # kept from file
    assert out.port == 9000
    assert out.enable_scheduler is True


def test_load_server_config_missing_returns_defaults(tmp_path: Path) -> None:
    cfg = load_server_config(tmp_path / "absent.toml")
    assert cfg == ServerConfig()


def test_load_server_config_explicit_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_server_config(tmp_path / "absent.toml", required=True)


def test_load_server_config_happy_path(tmp_path: Path) -> None:
    p = tmp_path / "server.toml"
    _write(
        p,
        """
transport = "http"
host = "192.0.2.1"
port = 9000
enable_scheduler = true
""",
    )
    cfg = load_server_config(p)
    assert cfg.transport is Transport.HTTP
    assert cfg.host == "192.0.2.1"
    assert cfg.port == 9000
    assert cfg.enable_scheduler is True


def test_load_server_config_rejects_unknown_field(tmp_path: Path) -> None:
    p = tmp_path / "server.toml"
    _write(p, 'transport = "stdio"\nfoo = 1\n')
    with pytest.raises(ConfigError):
        load_server_config(p)


def test_load_server_config_rejects_bad_toml(tmp_path: Path) -> None:
    p = tmp_path / "server.toml"
    _write(p, "this is not toml = [")
    with pytest.raises(ConfigError):
        load_server_config(p)


def test_discover_default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SEARCH_CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    path, explicit = discover_server_config_path(None)
    assert path == Path("./config/server.toml")
    assert explicit is False


def test_discover_cli_arg_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SEARCH_CONFIG_PATH", str(tmp_path / "from-env.toml"))
    path, explicit = discover_server_config_path(str(tmp_path / "from-cli.toml"))
    assert path == tmp_path / "from-cli.toml"
    assert explicit is True


def test_discover_env_when_no_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SEARCH_CONFIG_PATH", str(tmp_path / "from-env.toml"))
    path, explicit = discover_server_config_path(None)
    assert path == tmp_path / "from-env.toml"
    assert explicit is True
