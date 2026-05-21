"""Tests for Git URL generation per spec §6."""

from __future__ import annotations

import pytest

from codesearch_mcp.giturl import Hosting, build_url


def test_github_single_line() -> None:
    url = build_url(
        Hosting.GITHUB,
        base_url="https://github.com/example/main-app",
        branch="main",
        path="src/foo.py",
        start_line=42,
    )
    assert url == "https://github.com/example/main-app/blob/main/src/foo.py#L42"


def test_github_range() -> None:
    url = build_url(
        Hosting.GITHUB,
        base_url="https://github.com/example/main-app",
        branch="main",
        path="src/foo.py",
        start_line=40,
        end_line=45,
    )
    assert url == "https://github.com/example/main-app/blob/main/src/foo.py#L40-L45"


def test_gitlab_single_line() -> None:
    url = build_url(
        Hosting.GITLAB,
        base_url="https://gitlab.com/g/p",
        branch="main",
        path="src/foo.py",
        start_line=5,
    )
    assert url == "https://gitlab.com/g/p/-/blob/main/src/foo.py#L5"


def test_gitlab_range() -> None:
    url = build_url(
        Hosting.GITLAB,
        base_url="https://gitlab.com/g/p",
        branch="main",
        path="src/foo.py",
        start_line=5,
        end_line=9,
    )
    assert url == "https://gitlab.com/g/p/-/blob/main/src/foo.py#L5-9"


def test_bitbucket_single_line() -> None:
    url = build_url(
        Hosting.BITBUCKET,
        base_url="https://bitbucket.org/o/r",
        branch="develop",
        path="lib/x.ts",
        start_line=12,
    )
    assert url == "https://bitbucket.org/o/r/src/develop/lib/x.ts#lines-12"


def test_bitbucket_range() -> None:
    url = build_url(
        Hosting.BITBUCKET,
        base_url="https://bitbucket.org/o/r",
        branch="develop",
        path="lib/x.ts",
        start_line=12,
        end_line=18,
    )
    assert url == "https://bitbucket.org/o/r/src/develop/lib/x.ts#lines-12:18"


def test_gitea_single_line() -> None:
    url = build_url(
        Hosting.GITEA,
        base_url="https://gitea.local/o/r",
        branch="trunk",
        path="x.py",
        start_line=1,
    )
    assert url == "https://gitea.local/o/r/src/branch/trunk/x.py#L1"


def test_gitea_range() -> None:
    url = build_url(
        Hosting.GITEA,
        base_url="https://gitea.local/o/r",
        branch="trunk",
        path="x.py",
        start_line=1,
        end_line=3,
    )
    assert url == "https://gitea.local/o/r/src/branch/trunk/x.py#L1-L3"


def test_path_url_encoded_keeps_slash() -> None:
    url = build_url(
        Hosting.GITHUB,
        base_url="https://github.com/o/r",
        branch="main",
        path="dir with space/a#b%c.py",
        start_line=1,
    )
    assert url == "https://github.com/o/r/blob/main/dir%20with%20space/a%23b%25c.py#L1"


def test_path_url_encodes_non_ascii_utf8() -> None:
    url = build_url(
        Hosting.GITHUB,
        base_url="https://github.com/o/r",
        branch="main",
        path="ディレクトリ/ファイル.py",
        start_line=1,
    )
    assert (
        url
        == "https://github.com/o/r/blob/main/%E3%83%87%E3%82%A3%E3%83%AC%E3%82%AF%E3%83%88%E3%83%AA/%E3%83%95%E3%82%A1%E3%82%A4%E3%83%AB.py#L1"
    )


def test_base_url_trailing_slash_trimmed() -> None:
    url = build_url(
        Hosting.GITHUB,
        base_url="https://github.com/o/r/",
        branch="main",
        path="a.py",
        start_line=2,
    )
    assert url == "https://github.com/o/r/blob/main/a.py#L2"


def test_end_line_equal_to_start_line_treated_as_single() -> None:
    url = build_url(
        Hosting.GITHUB,
        base_url="https://github.com/o/r",
        branch="main",
        path="a.py",
        start_line=5,
        end_line=5,
    )
    assert url == "https://github.com/o/r/blob/main/a.py#L5"


def test_invalid_hosting_string_rejected_by_enum() -> None:
    with pytest.raises(ValueError):
        Hosting("hg")
