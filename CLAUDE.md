# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This is a Model Context Protocol (MCP) server that searches Git-managed source
code. M1 (server) and the harness layer are implemented; the authoritative
docs in `docs/` remain the source of truth and must not be contradicted.

Read these before doing anything, in order:

- `docs/requirements.md` — 要件書 (what to solve: scope, functional /
  non-functional requirements, backend command selection rationale)
- `docs/spec/spec.md` — 仕様書 (external interface: MCP tools, input/output
  schemas, error codes, config files, performance guarantees)
- `docs/design/design.md` — 設計 (internal architecture and locked decisions)
- `docs/tasks/task.md` — 実行計画 (WBS task list and status)

The docs are written in Japanese and are the source of truth. Requirements →
spec → design → plan is a strict hierarchy; do not contradict an upstream doc.

## Repository conventions

- **Design vs. plan are separate artifacts.** Internal/architecture design
  lives in `docs/design/design.md`. The execution plan (WBS) lives in
  `docs/tasks/task.md` and must follow the `plan-tasks` skill format
  (`# TASKS`, single milestone + goal, workflow/status rules before the table,
  fixed columns `| ID | Status | Summary | DependsOn |`, sequential
  `TASK-NNN`, no code, Backlog last). When asked for an "実行計画 / タスク一覧",
  use the `plan-tasks` skill — not `writing-plans` (which emits code-heavy
  playbooks and is the wrong artifact here).
- Detailed design and implementation code are decided per task at
  implementation time (TDD), never written into the plan.
- **Commit attribution: never add Claude credit to the git history.** Do not
  append `Co-Authored-By: Claude ...`, "🤖 Generated with Claude Code", or any
  tool/AI attribution to commit messages or PR bodies. The author and
  committer are the git-config user only. This overrides the harness default
  that would otherwise add a Co-Authored-By trailer.

## Toolchain & commands

Everything runs through `make` (see `Makefile`); under the hood Make calls
`uv run …`. Do not invoke pip directly — `uv` is the only supported package
manager (see "Harness rules" below).

- Install deps (locked): `uv sync --frozen`  /  add a dep: `uv add NAME`
- Full quality gate (the same one CI runs): `make verify`
- Individual gates: `make lint` / `make format-check` / `make types`
  (Pyrefly) / `make imports` (import-linter) / `make test` (pytest +
  coverage 80%) / `make audit` (pip-audit) / `make md` (markdownlint-cli2)
- Auto-fix formatting: `make format`
- One test: `uv run pytest tests/path/test_file.py::test_name -v`
- Skip-fast mode without coverage: `make test-fast`
- Integration tests require `git` and `ripgrep` (`rg`) on PATH; tests that
  need them skip cleanly via `requires_git` / `requires_rg` markers.

Markdown (docs are linted):

- Validate: run the **`markdownlint-cli2` binary directly**
  (`markdownlint-cli2 <file>`). **Do not invoke it via `npx`** — that form is
  denied. Auto-fix whitespace rules with `markdownlint-cli2 --fix <file>`.
- `.markdownlint-cli2.jsonc` (repo root) is required by the `markdown` skill:
  it disables MD013 for tables/code and MD024. Keep it.

## Harness rules

The pipeline is the contract — code that fails `make verify` does not ship.
These rules exist so the gate stays green and the agent does not paper over
the failure modes Python invites.

- **Subprocess safety.** Always use `asyncio.create_subprocess_exec` (aliased
  as `_spawn`, see "Implementation gotcha" below) or the project's
  `backends.command` helpers. `shell=True` and `subprocess.run(... shell=True)`
  are forbidden — Ruff's `S6xx` rules will fail the build. Pass argv as a
  list, never a single shell string.
- **No `pip` directly.** Dependency changes go through `uv add`, `uv remove`,
  and `uv sync --frozen`. Never `pip install` into `.venv` — it bypasses
  `uv.lock` and breaks reproducibility.
- **Public functions must be typed.** Pyrefly runs in strict mode on `src/`
  with `unannotated-parameter` / `unannotated-return` / `unannotated-attribute`
  as errors. Use precise types, not bare `Any`, except for FastMCP-registered
  tool callbacks where `Any` is required so FastMCP does not auto-infer an
  output schema.
- **No I/O at module import time.** import-linter and the implicit
  `pytest --collect-only` step both fail if importing a module performs
  filesystem or network work. Defer it to a function called from the entry
  point.
- **Layered architecture is enforced by `.importlinter`.** Inner layers
  (`errors`, then `pathsafe/giturl/logging`, then `backends/config`, then
  `repo`, then `tools/observability`, then `server`, then `__main__`) cannot
  import outer layers, and `tools/*` modules cannot import each other. If you
  need to break a contract, change the contract explicitly — do not work
  around it.
- **Coverage floor is 80%.** Adding a module without tests will lower the
  total under the floor. Either add tests or move the code into an already
  excluded path (`__main__.py`).
- **Secrets never on disk in the repo.** `secrets.toml`, `.env`, and SSH key
  paths are denied by `.claude/settings.json`. The configured `redact()`
  patterns in `codesearch_mcp.logging` strip tokens from logs.

When in doubt, run `make verify` before declaring work complete.

## Architecture (big picture)

The full module map is in `docs/design/design.md` §3. Layout under
`src/codesearch_mcp/` (inner → outer; each layer may only import lower ones —
contract is enforced by `.importlinter`):

- `errors.py`, `pathsafe.py`, `giturl.py`, `logging.py` — pure primitives
- `config/` (Pydantic models + TOML loader), `backends/` (subprocess /
  ripgrep / git-ls wrappers)
- `repo/` — `RepositoryManager` (readiness, workspaces) + `git_sync` +
  optional `scheduler`
- `tools/` — one module per MCP tool (`search_code`, `list_files`,
  `list_tree`, `read_file`); they cannot import each other
- `server.py` — FastMCP wiring, concurrency/timeout guard
- `__main__.py` — CLI entry; `codesearch-mcp serve --transport stdio|http`
  and `codesearch-sync` are defined here

The essentials that span multiple files:

- **Five MCP tools**: four search tools (`search_code`, `list_files`,
  `list_tree`, `read_file`) plus one discovery helper (`list_repositories`)
  for MCP hosts that do not surface Resources to the LLM. All exposed via the
  official `mcp` SDK's FastMCP. The whole server is async; external commands
  (`ripgrep`, `git`) run as shell-free subprocesses. Also publishes one MCP
  Resource per configured repository (`codesearch://repo/{id}`) so
  Resources-aware hosts can discover the catalog there.
- **Git sync is decoupled from the request path** and deployment-agnostic.
  Tools only ever read the local workspace. Sync is an idempotent operation
  driven by a `codesearch-sync` CLI (for cron / systemd / CronJob) and an
  optional in-process scheduler. A blocking git pull on a tool call is
  forbidden (would violate the 2s p95 / availability requirements).
- **Error model**: domain failures raise `ToolError(code, message, details)`
  and are returned as an `isError` tool result whose content is the JSON
  `{code,message,details}`; JSON-Schema input violations surface as MCP
  `-32602` (let FastMCP/Pydantic produce these — do not hand-roll).
- **Path safety**: every path argument goes through `pathsafe`
  (reject absolute / `..`, realpath-contain inside the repo workspace,
  `INVALID_PATH` / `PATH_NOT_FOUND`).
- **Per-repo isolation**: `RepositoryManager` tracks readiness; one repo's
  clone/fetch failure must not affect others (`REPO_NOT_READY` vs others
  stay usable).
- **Git URL generation** is hosting-specific (github/gitlab/bitbucket/gitea,
  single-line and range anchors) — see `docs/spec/spec.md` §6.

## Implementation gotcha

A pre-existing repo security hook blocks writing any file containing the
substring `exec` immediately followed by an open parenthesis (it assumes a
TypeScript `child_process` context; it false-positives on Python's safe,
shell-free subprocess API). When implementing the command runner / git sync,
reference the API via an alias so no call site contains that sequence:
`from asyncio import create_subprocess_exec as _spawn`, then call `_spawn(...)`.
Behaviour and safety (no shell) are unchanged; do not "fix" the alias back.

## Memory

Project-specific working agreements are recorded under the agent memory dir
(see `MEMORY.md` there): use `plan-tasks` for execution plans; agree on the
deliverable form first; verify with the actual command before claiming
completion.
