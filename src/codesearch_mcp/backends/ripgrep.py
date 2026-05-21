"""ripgrep argv construction and --json output parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class RgMatch:
    file_path: str
    line_number: int
    line_content: str


@dataclass(slots=True)
class RgContextLine:
    file_path: str
    line_number: int
    content: str


def build_search_argv(
    *,
    pattern: str,
    path: str | None,
    glob: str | None,
    type_: str | None,
    case_sensitive: bool,
    context_before: int,
    context_after: int,
    max_count: int,
    mode: Literal["content", "files_with_matches", "count"],
) -> list[str]:
    """Construct ripgrep argv. ``path`` is the relative path inside the workspace.

    The caller is responsible for resolving the workspace cwd separately.
    """

    argv: list[str] = [
        "rg",
        "--json",
        "--no-messages",
        "--no-heading",
        "--no-config",
    ]
    if case_sensitive:
        argv.append("--case-sensitive")
    else:
        argv.append("--ignore-case")
    # We always run --json (without --files-with-matches/--count-matches,
    # which would override JSON output). Aggregation happens in the caller.
    if mode == "content":
        if context_before > 0:
            argv += ["--before-context", str(context_before)]
        if context_after > 0:
            argv += ["--after-context", str(context_after)]
    if glob:
        argv += ["--glob", glob]
    if type_:
        argv += ["--type", type_]
    # Cap per-file matches to bound output size.
    argv += ["--max-count", str(max_count)]
    argv += ["--regexp", pattern, "--"]
    argv.append(path if path else ".")
    return argv


def build_files_argv(
    *,
    pattern: str,
    path: str | None,
    follow_gitignore: bool = False,
) -> list[str]:
    """Construct ``rg --files`` argv for list_files."""

    argv: list[str] = [
        "rg",
        "--files",
        "--no-messages",
        "--no-config",
        "--glob",
        pattern,
        "--hidden",
    ]
    if not follow_gitignore:
        argv += ["--no-ignore-vcs", "--no-ignore"]
    argv += ["--", path if path else "."]
    return argv


@dataclass(slots=True)
class ParsedSearch:
    matches: list[RgMatch]
    files_with_matches: list[str]
    counts: dict[str, int]
    contexts: list[RgContextLine]


def _text_field(field: dict) -> str:
    if "text" in field:
        return field["text"]
    if "bytes" in field:
        import base64

        return base64.b64decode(field["bytes"]).decode("utf-8", errors="replace")
    return ""


def _strip_dot_prefix(p: str) -> str:
    if p.startswith("./"):
        return p[2:]
    return p


def parse_rg_json(stdout: bytes) -> ParsedSearch:
    matches: list[RgMatch] = []
    files: list[str] = []
    counts: dict[str, int] = {}
    contexts: list[RgContextLine] = []

    for raw in stdout.splitlines():
        if not raw:
            continue
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = evt.get("type")
        data = evt.get("data", {})
        if kind == "begin":
            # Path is re-extracted from each match/context/end event below.
            continue
        if kind == "match":
            file_path = _strip_dot_prefix(_text_field(data.get("path", {})))
            line_number = int(data.get("line_number") or 0)
            line_content = _text_field(data.get("lines", {})).rstrip("\n")
            matches.append(
                RgMatch(
                    file_path=file_path,
                    line_number=line_number,
                    line_content=line_content,
                )
            )
        elif kind == "context":
            file_path = _strip_dot_prefix(_text_field(data.get("path", {})))
            line_number = int(data.get("line_number") or 0)
            content = _text_field(data.get("lines", {})).rstrip("\n")
            contexts.append(
                RgContextLine(
                    file_path=file_path,
                    line_number=line_number,
                    content=content,
                )
            )
        elif kind == "end":
            file_path = _strip_dot_prefix(_text_field(data.get("path", {})))
            stats = data.get("stats", {})
            n = int(stats.get("matches") or 0)
            if n > 0:
                files.append(file_path)
                counts[file_path] = n
    return ParsedSearch(
        matches=matches,
        files_with_matches=files,
        counts=counts,
        contexts=contexts,
    )
