# Changelog

All notable user-facing changes to this MCP server.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/).

Only changes visible to MCP clients / operators / configuration users are
recorded here. Internal refactoring is omitted.

## [Unreleased]

## [0.2.0] - 2026-10-20

### Added

- `list_repositories` tool (5th tool) exposing the configured repository
  catalog through the MCP tools surface so hosts that do not forward
  Resources to the LLM can still discover repository ids.
- MCP **Resources** capability (`codesearch://repo/{id}`) advertising each
  configured repository with its branch, hosting metadata, sync status, and
  operator-supplied description.
- `RepositoryConfig.description` field (optional, ≤8192 chars) carried into
  Resources and `list_repositories` so the LLM can choose the right
  repository for a query.
- Server `instructions` and rich per-tool `description` strings published via
  `initialize` / `tools/list`.
- HTTP authentication patterns (reverse-proxy Bearer / mTLS / OAuth proxy)
  documented in `docs/operations.md`.
- Reference client `scripts/probe.py` for verifying a running server without
  an MCP host application.
- Dockerfile + `examples/docker-compose.yml` for the canonical container
  deployment.

### Changed

- `serverInfo.version` reported by `initialize` now reflects this project's
  `codesearch_mcp.__version__` instead of the MCP SDK version.
- `capabilities.prompts` is no longer advertised (Spec §2.2 requires only
  `tools` and `resources`).
- Upgraded the MCP Python SDK to 2.x (`mcp>=2.3,<3`). The server now also
  serves the 2026-07-28 protocol revision (`server/discover`, per-request
  Streamable HTTP) in addition to the `initialize` handshake.
- Verified on Python 3.11 through 3.15 (`requires-python` stays `>=3.11`).
- `tools/call` with an unknown tool name now returns a JSON-RPC protocol
  error (`-32602`, `Unknown tool: <name>`) instead of an `isError` tool
  result, as the MCP spec requires. Argument validation failures remain
  `isError` tool results (Spec §5.4).
- `search_code`'s `outputSchema` now declares `"type": "object"` at the
  root, as MCP requires.
- `resources.subscribe` and `listChanged` are advertised as `false`: the
  server emits no change notifications.

### Removed

- Nothing yet.

## [0.1.0] - 2026-05-19

Initial preview release. Implements the four core search tools
(`search_code`, `list_files`, `list_tree`, `read_file`) and the
`codesearch-mcp` / `codesearch-sync` CLIs.
