# LLM 向け利用ガイダンス

This document is the human-readable mirror of the strings advertised through
MCP capability discovery (server `instructions` and per-tool `description`).

ソース・オブ・トゥルースは `src/codesearch_mcp/llm_guidance.py`。
変更はそちらと本書を同時に行い、`tests/test_tool_descriptions.py` の
キーフレーズ照合で同期を担保する。

本文書全体は **英語** で記す。MCP クライアント (LLM) に届くテキストと
1:1 で対応させたいため。

## Server instructions (advertised at `initialize`)

```text
Use this MCP server when investigating Git-managed source code in the configured
repositories. The intended workflow on an unfamiliar repository is:

  1. resources/list to discover which repositories are available (each one is
     advertised at codesearch://repo/{id}; the id is the `repository` argument
     for every tool below)
  2. list_tree     to orient yourself in the directory layout
  3. search_code   to locate a symbol, error string, or distinctive token
  4. read_file     to inspect the surrounding lines with citation-ready Git URLs

list_files complements list_tree when filename-based lookup is more useful than
a content search. resources/read on a repository URI returns its sync status,
branch, and hosting metadata when you need to verify freshness.

What this server does NOT do (delegate to a different MCP if you need them):
- natural-language / semantic search
- vector embedding lookup or chunk summarisation
- code generation, editing, or commits
- reading binary files (images, PDFs, executables) — text only

Returned `git_url` fields are stable citation links and should be quoted back
to the user verbatim. Domain failures arrive as `isError: true` tool results
whose content is a JSON `{code, message, details}` string (see spec §5.2).
```

## Tool: `search_code`

```text
Search file contents using a regular expression. Use this when you know a
distinctive token (symbol name, error message fragment, log key) and want to
find every place it occurs.

The `repository` argument must be one of the configured repository ids — call
resources/list first if you do not yet know which are available (each is
advertised at codesearch://repo/{id}).

Tips:
- output_mode='content' (default) returns hit lines, optionally with
  context_before/after for surrounding lines.
- output_mode='files_with_matches' is cheaper when you only need WHICH files
  contain the pattern.
- output_mode='count' reports per-file match counts, useful for ranking files
  by relevance.
- Constrain with `glob` ('**/*.py') or `type` ('python') to scope by language.
- Returns at most max_results (default 50, hard cap 500); truncated=true
  signals the limit was hit.

Choose list_files instead when you are searching by FILE NAME, and read_file
to retrieve the wider context around any single hit.
```

## Tool: `list_files`

```text
List files in a repository by filename glob. Use this when you want to find
files by NAME — e.g. every *Controller.ts, all package.json files, or files
matching src/main/**/*.java.

The `repository` argument must be one of the configured repository ids —
discover them via resources/list (codesearch://repo/{id}).

Returns each match with last_modified (sorted newest first) so you can pick the
freshest file when multiple match.

Choose search_code instead when you are matching file CONTENTS. Choose
list_tree to first survey the directory layout before deciding what to glob.
```

## Tool: `list_tree`

```text
Render a directory tree of a repository. Use this FIRST on an unfamiliar
repository to see which directories are worth drilling into. Only tracked
files appear; untracked and gitignored entries are excluded.

The `repository` argument must be one of the configured repository ids —
discover them via resources/list (codesearch://repo/{id}).

Tune the output:
- max_depth (default 2, cap 5) — how many levels to descend
- show_files=false — directories only, when the file list would be noisy
- max_entries (default 200, cap 1000) — truncated=true if exceeded

After list_tree narrows the scope, use search_code to look inside or list_files
to enumerate by name.
```

## Tool: `read_file`

```text
Read a line range from a tracked file and return it with line numbers plus a
Git URL anchored to that range. Use this after search_code or list_files
narrows the target, or directly when you already know the path.

The `repository` argument must be one of the configured repository ids —
discover them via resources/list (codesearch://repo/{id}).

Constraints (hard errors):
- File size must be under 10 MiB → FILE_TOO_LARGE otherwise.
- File must decode as UTF-8 → FILE_BINARY otherwise.
- num_lines is capped at 2000.

Prefer a narrow start_line / num_lines window; quote the returned git_url back
to the user as the citation rather than reproducing the whole file.
```

## Tool: `list_repositories`

```text
Return the catalog of configured repositories — the same data that
resources/list advertises, but as a regular tool call so it is visible to MCP
host applications that do not surface Resources to the LLM.

Use this FIRST in a fresh conversation if you do not yet know which
`repository` ids are valid. Each entry contains id, branch, hosting_base_url,
exclude_paths, refresh_interval_seconds, and a status snapshot
(state / last_sync_at / last_outcome / last_error / last_commit) so you can
choose a repo that is actually ready before searching.

This tool takes no arguments. It is a discovery aid; it does not search or
read files itself.
```

## Resources: repository catalog

The server also advertises one Resource per configured repository at
`codesearch://repo/{id}`. Listing them is how an LLM discovers what
`repository` values are valid. Reading a resource returns a JSON object
with branch, hosting metadata, and sync status (state, last_sync_at,
last_outcome, last_error, last_commit), useful for verifying freshness
before search.
