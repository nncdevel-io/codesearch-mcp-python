"""Repository catalog exposed as MCP Resources.

Each configured repository is advertised as ``codesearch://repo/{id}`` so the
LLM (and any MCP client) can discover the set of valid ``repository`` arguments
*without* parsing the human-facing README. The body of each resource is the
sync-status snapshot for that repository (state / last_outcome / last_commit /
last_sync_at / last_error / branch / hosting_base_url), JSON-encoded.

This is the implementation side of harness-report-tracked TASK-067 and is
documented in ``docs/usage-for-llm.md``.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource
from pydantic import AnyUrl

from .config.models import Settings
from .observability import sync_status_report
from .repo.manager import RepositoryManager

REPO_URI_SCHEME = "codesearch"
REPO_URI_HOST = "repo"


def repo_uri(repo_id: str) -> str:
    return f"{REPO_URI_SCHEME}://{REPO_URI_HOST}/{repo_id}"


def _entry_for(manager: RepositoryManager, repo_id: str) -> dict[str, Any]:
    """Build the JSON body returned by `resources/read` for one repo."""

    cfg = manager.config(repo_id)
    status = next(
        (s for s in sync_status_report(manager) if s["repository"] == repo_id),
        None,
    )
    return {
        "id": cfg.id,
        "branch": cfg.branch,
        "hosting": cfg.hosting.value,
        "hosting_base_url": cfg.hosting_base_url,
        "exclude_paths": list(cfg.exclude_paths),
        "refresh_interval_seconds": cfg.refresh_interval_seconds,
        "description": cfg.description,
        "status": status,
    }


def repository_catalog(manager: RepositoryManager) -> list[dict[str, Any]]:
    """All configured repositories with metadata + sync status.

    Same data as `resources/read` for every URI, but as a flat list — used by
    the `list_repositories` tool so the catalog is reachable from MCP hosts
    that do not surface Resources to the LLM.
    """

    return [_entry_for(manager, rid) for rid in manager.ids()]


def register_repository_resources(
    mcp: FastMCP,
    settings: Settings,
    manager: RepositoryManager,
) -> None:
    """Register one ``codesearch://repo/{id}`` Resource per configured repo.

    Resources are registered statically at server build time. They are not
    list-changed-notified (the catalog is fixed for the process lifetime).
    """

    for repo_cfg in settings.repositories:
        rid = repo_cfg.id

        # Closure-capture by default arg to avoid the late-binding trap.
        def _read(repo_id: str = rid) -> str:
            return json.dumps(
                _entry_for(manager, repo_id),
                ensure_ascii=False,
                separators=(",", ":"),
            )

        if repo_cfg.description:
            # Operator-supplied (typically AI-generated) summary. This is what
            # the LLM sees in resources/list when choosing a repo.
            advertised_description = repo_cfg.description
        else:
            advertised_description = (
                f"Configured Git repository '{rid}'. "
                f"Use this id as the `repository` argument to any tool. "
                f"Reading the resource returns sync status, branch, and hosting metadata."
            )

        resource = FunctionResource(
            uri=AnyUrl(repo_uri(rid)),
            name=f"Repository: {rid}",
            title=rid,
            description=advertised_description,
            mime_type="application/json",
            fn=_read,
        )
        mcp.add_resource(resource)
