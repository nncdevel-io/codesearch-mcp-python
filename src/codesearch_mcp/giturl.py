"""Git URL generation per spec §6 for github/gitlab/bitbucket/gitea."""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import quote


class Hosting(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GITEA = "gitea"


def _encode_path(path: str) -> str:
    # Preserve '/' separators; percent-encode spaces, reserved chars, and non-ASCII.
    return quote(path, safe="/")


def build_url(
    hosting: Hosting,
    *,
    base_url: str,
    branch: str,
    path: str,
    start_line: int,
    end_line: int | None = None,
) -> str:
    base = base_url.rstrip("/")
    encoded_path = _encode_path(path)
    is_range = end_line is not None and end_line != start_line

    if hosting is Hosting.GITHUB:
        prefix = f"{base}/blob/{branch}/{encoded_path}"
        anchor = f"#L{start_line}-L{end_line}" if is_range else f"#L{start_line}"
    elif hosting is Hosting.GITLAB:
        prefix = f"{base}/-/blob/{branch}/{encoded_path}"
        anchor = f"#L{start_line}-{end_line}" if is_range else f"#L{start_line}"
    elif hosting is Hosting.BITBUCKET:
        prefix = f"{base}/src/{branch}/{encoded_path}"
        anchor = f"#lines-{start_line}:{end_line}" if is_range else f"#lines-{start_line}"
    elif hosting is Hosting.GITEA:
        prefix = f"{base}/src/branch/{branch}/{encoded_path}"
        anchor = f"#L{start_line}-L{end_line}" if is_range else f"#L{start_line}"
    else:  # pragma: no cover - exhaustive enum
        raise ValueError(f"unsupported hosting: {hosting!r}")

    return prefix + anchor
