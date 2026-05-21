"""list_tree tool implementation: build an ASCII directory tree from git ls-files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..backends.git_ls import list_tracked_files
from ..errors import ErrorCode, ToolError
from ..pathsafe import normalize_relative, resolve_within_workspace
from ..repo.manager import RepositoryManager
from .schemas import ListTreeInput


@dataclass(slots=True)
class _Node:
    name: str
    is_dir: bool
    children: dict[str, _Node] = field(default_factory=dict)


def _insert_path(root: _Node, parts: list[str]) -> None:
    cur = root
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        existing = cur.children.get(part)
        if existing is None:
            existing = _Node(name=part, is_dir=not is_last)
            cur.children[part] = existing
        if not is_last:
            existing.is_dir = True
        cur = existing


def build_tree_text(
    rel_paths: list[str],
    *,
    root_label: str,
    max_depth: int,
    show_files: bool,
    max_entries: int,
    exclude_prefixes: tuple[str, ...] = (),
) -> tuple[str, bool, int]:
    """Return (text, truncated, entry_count). Sorts by Unicode code point."""

    root = _Node(name=root_label or ".", is_dir=True)
    for rel in rel_paths:
        if not rel:
            continue
        if exclude_prefixes and any(
            rel == p.rstrip("/") or rel.startswith(p) for p in exclude_prefixes
        ):
            continue
        parts = rel.split("/")
        _insert_path(root, parts)

    lines: list[str] = []
    entry_count = 0
    truncated = False

    label = root.name.rstrip("/") + "/"
    lines.append(label)

    def emit(node: _Node, prefix: str, depth: int) -> None:
        nonlocal entry_count, truncated
        if depth > max_depth:
            return
        children = sorted(node.children.values(), key=lambda n: n.name)
        if not show_files:
            children = [c for c in children if c.is_dir]
        for i, child in enumerate(children):
            if entry_count >= max_entries:
                truncated = True
                return
            is_last = i == len(children) - 1
            branch = "└── " if is_last else "├── "
            name = child.name + ("/" if child.is_dir else "")
            lines.append(prefix + branch + name)
            entry_count += 1
            if child.is_dir:
                next_prefix = prefix + ("    " if is_last else "│   ")
                emit(child, next_prefix, depth + 1)
                if truncated:
                    return

    emit(root, "", 1)
    return "\n".join(lines), truncated, entry_count


async def execute_list_tree(manager: RepositoryManager, payload: ListTreeInput) -> dict[str, Any]:
    workspace = manager.require_ready(payload.repository)
    repo_cfg = manager.config(payload.repository)
    rel_root = normalize_relative(payload.path) if payload.path else ""
    if rel_root:
        resolved = resolve_within_workspace(workspace, rel_root)
        if not resolved.is_dir():
            raise ToolError(
                ErrorCode.PATH_NOT_FOUND,
                "list_tree path must be a directory",
                {"path": rel_root},
            )

    files = await list_tracked_files(workspace, subpath=rel_root or None)
    if rel_root:
        prefix = rel_root + "/"
        files = [f.removeprefix(prefix) for f in files if f == rel_root or f.startswith(prefix)]

    tree_text, truncated, entry_count = build_tree_text(
        files,
        root_label=rel_root or repo_cfg.id,
        max_depth=payload.max_depth,
        show_files=payload.show_files,
        max_entries=payload.max_entries,
        exclude_prefixes=tuple(repo_cfg.exclude_paths),
    )
    return {
        "repository": payload.repository,
        "root_path": rel_root,
        "tree": tree_text,
        "truncated": truncated,
        "entry_count": entry_count,
    }
