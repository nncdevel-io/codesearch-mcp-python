"""search_code tool implementation."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..backends.command import base_env, run_command
from ..backends.ripgrep import (
    ParsedSearch,
    RgContextLine,
    build_search_argv,
    parse_rg_json,
)
from ..config.models import RepositoryConfig
from ..errors import ErrorCode, ToolError
from ..giturl import build_url
from ..pathsafe import normalize_relative
from ..repo.manager import RepositoryManager
from .schemas import SearchCodeInput

_SEARCH_TIMEOUT_SECONDS = 9.0


def _git_url(
    repo: RepositoryConfig,
    file_path: str,
    start_line: int,
    end_line: int | None = None,
) -> str:
    return build_url(
        repo.hosting,
        base_url=repo.hosting_base_url,
        branch=repo.branch,
        path=file_path,
        start_line=start_line,
        end_line=end_line,
    )


def _excluded(path: str, exclude_prefixes: tuple[str, ...]) -> bool:
    for prefix in exclude_prefixes:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return True
    return False


async def _run_ripgrep(
    workspace: Path,
    argv: list[str],
    *,
    timeout: float,
) -> ParsedSearch:
    res = await run_command(argv, cwd=workspace, env=base_env(), timeout=timeout)
    # ripgrep exit codes: 0=matches, 1=no matches, 2=error
    if res.returncode == 2:
        stderr = res.stderr.decode("utf-8", errors="replace").strip()
        if "regex parse error" in stderr.lower() or "error parsing regex" in stderr.lower():
            raise ToolError(
                ErrorCode.INVALID_PATTERN,
                "search pattern is invalid",
                {"stderr": stderr.splitlines()[-1] if stderr else ""},
            )
        raise ToolError(
            ErrorCode.BACKEND_FAILURE,
            "ripgrep exited with error",
            {"stderr": stderr.splitlines()[-1] if stderr else ""},
        )
    return parse_rg_json(res.stdout)


def _normalize_subpath(path: str | None) -> str | None:
    if path is None or path == "":
        return None
    return normalize_relative(path)


def _group_contexts_by_match(
    matches: list, contexts: list[RgContextLine]
) -> dict[tuple[str, int], dict[str, list[dict[str, Any]]]]:
    """Attach context lines to the nearest match per file."""

    by_file: dict[str, list[int]] = defaultdict(list)
    for m in matches:
        by_file[m.file_path].append(m.line_number)

    out: dict[tuple[str, int], dict[str, list[dict[str, Any]]]] = {}
    for m in matches:
        out[(m.file_path, m.line_number)] = {"before": [], "after": []}

    for ctx in contexts:
        match_lines = by_file.get(ctx.file_path) or []
        if not match_lines:
            continue
        # Find the nearest match line
        nearest = min(match_lines, key=lambda ml: abs(ml - ctx.line_number))
        bucket = "before" if ctx.line_number < nearest else "after"
        out[(ctx.file_path, nearest)][bucket].append(
            {"line_number": ctx.line_number, "content": ctx.content}
        )
    return out


async def execute_search_code(
    manager: RepositoryManager, payload: SearchCodeInput
) -> dict[str, Any]:
    workspace = manager.require_ready(payload.repository)
    repo_cfg = manager.config(payload.repository)
    subpath = _normalize_subpath(payload.path)

    # We use the per-file max-count; results will be globally truncated below.
    argv = build_search_argv(
        pattern=payload.pattern,
        path=subpath,
        glob=payload.glob,
        type_=payload.type,
        case_sensitive=payload.case_sensitive,
        context_before=payload.context_before,
        context_after=payload.context_after,
        max_count=payload.max_results,
        mode=payload.output_mode,
    )
    parsed = await _run_ripgrep(workspace, argv, timeout=_SEARCH_TIMEOUT_SECONDS)
    exclude = tuple(repo_cfg.exclude_paths)

    if payload.output_mode == "files_with_matches":
        files = [f for f in parsed.files_with_matches if not _excluded(f, exclude)]
        truncated = len(files) > payload.max_results
        files = files[: payload.max_results]
        return {
            "files": [
                {
                    "repository": payload.repository,
                    "file_path": f,
                    "git_url": _git_url(repo_cfg, f, 1),
                }
                for f in files
            ],
            "truncated": truncated,
        }

    if payload.output_mode == "count":
        items: list[dict[str, Any]] = []
        for f, n in parsed.counts.items():
            if _excluded(f, exclude):
                continue
            items.append(
                {
                    "repository": payload.repository,
                    "file_path": f,
                    "match_count": n,
                    "git_url": _git_url(repo_cfg, f, 1),
                }
            )
        items.sort(key=lambda d: (-d["match_count"], d["file_path"]))
        truncated = len(items) > payload.max_results
        items = items[: payload.max_results]
        return {"files": items, "truncated": truncated}

    # content mode
    filtered = [m for m in parsed.matches if not _excluded(m.file_path, exclude)]
    total = len(filtered)
    truncated = total > payload.max_results
    selected = filtered[: payload.max_results]
    grouped = _group_contexts_by_match(selected, parsed.contexts)
    out_matches: list[dict[str, Any]] = []
    for m in selected:
        ctx = grouped.get((m.file_path, m.line_number), {"before": [], "after": []})
        ctx_before = sorted(ctx["before"], key=lambda c: c["line_number"])
        ctx_after = sorted(ctx["after"], key=lambda c: c["line_number"])
        is_range = bool(ctx_before or ctx_after)
        if is_range:
            start_line = min([m.line_number] + [c["line_number"] for c in ctx_before])
            end_line = max([m.line_number] + [c["line_number"] for c in ctx_after])
            url = _git_url(repo_cfg, m.file_path, start_line, end_line)
        else:
            url = _git_url(repo_cfg, m.file_path, m.line_number)
        out_matches.append(
            {
                "repository": payload.repository,
                "file_path": m.file_path,
                "line_number": m.line_number,
                "line_content": m.line_content,
                "context_before": ctx_before,
                "context_after": ctx_after,
                "git_url": url,
            }
        )
    return {
        "matches": out_matches,
        "truncated": truncated,
        "total_matches": total,
    }
