"""Tests for ripgrep argv builders and JSON parser."""

from __future__ import annotations

import json

from codesearch_mcp.backends.ripgrep import (
    build_files_argv,
    build_search_argv,
    parse_rg_json,
)


def test_search_argv_default_is_case_insensitive_content() -> None:
    argv = build_search_argv(
        pattern="foo",
        path=None,
        glob=None,
        type_=None,
        case_sensitive=False,
        context_before=0,
        context_after=0,
        max_count=50,
        mode="content",
    )
    assert argv[0] == "rg"
    assert "--json" in argv
    assert "--ignore-case" in argv
    assert "--max-count" in argv
    assert argv[-2:] == ["--", "."]
    assert "--regexp" in argv
    assert argv[argv.index("--regexp") + 1] == "foo"


def test_search_argv_case_sensitive_and_glob_and_type() -> None:
    argv = build_search_argv(
        pattern="Foo",
        path="src",
        glob="**/*.java",
        type_="java",
        case_sensitive=True,
        context_before=2,
        context_after=3,
        max_count=10,
        mode="content",
    )
    assert "--case-sensitive" in argv
    assert "--ignore-case" not in argv
    assert "--glob" in argv and argv[argv.index("--glob") + 1] == "**/*.java"
    assert "--type" in argv and argv[argv.index("--type") + 1] == "java"
    assert "--before-context" in argv
    assert "--after-context" in argv
    assert argv[-1] == "src"


def test_search_argv_files_with_matches_mode_omits_context() -> None:
    argv = build_search_argv(
        pattern="x",
        path=None,
        glob=None,
        type_=None,
        case_sensitive=False,
        context_before=2,
        context_after=2,
        max_count=10,
        mode="files_with_matches",
    )
    # Summary-mode flags must NOT be passed because they suppress --json output.
    assert "--files-with-matches" not in argv
    assert "--before-context" not in argv
    assert "--after-context" not in argv


def test_search_argv_count_mode_uses_count_matches() -> None:
    argv = build_search_argv(
        pattern="x",
        path=None,
        glob=None,
        type_=None,
        case_sensitive=False,
        context_before=0,
        context_after=0,
        max_count=10,
        mode="count",
    )
    # Same: count mode must not strip JSON output by passing --count-matches.
    assert "--count-matches" not in argv


def test_files_argv_includes_hidden_and_ignores_vcs() -> None:
    argv = build_files_argv(pattern="**/*.py", path="src")
    assert argv[:2] == ["rg", "--files"]
    assert "--hidden" in argv
    assert "--no-ignore-vcs" in argv
    assert "--no-ignore" in argv
    assert "--glob" in argv and argv[argv.index("--glob") + 1] == "**/*.py"
    assert argv[-1] == "src"


def test_parse_rg_json_extracts_matches_and_contexts_and_counts() -> None:
    events = [
        {"type": "begin", "data": {"path": {"text": "a.py"}}},
        {
            "type": "context",
            "data": {
                "path": {"text": "a.py"},
                "lines": {"text": "before line\n"},
                "line_number": 9,
            },
        },
        {
            "type": "match",
            "data": {
                "path": {"text": "a.py"},
                "lines": {"text": "matched line\n"},
                "line_number": 10,
            },
        },
        {
            "type": "context",
            "data": {
                "path": {"text": "a.py"},
                "lines": {"text": "after line\n"},
                "line_number": 11,
            },
        },
        {
            "type": "end",
            "data": {"path": {"text": "a.py"}, "stats": {"matches": 1}},
        },
    ]
    stdout = "\n".join(json.dumps(e) for e in events).encode("utf-8")
    result = parse_rg_json(stdout)
    assert len(result.matches) == 1
    assert result.matches[0].file_path == "a.py"
    assert result.matches[0].line_number == 10
    assert result.matches[0].line_content == "matched line"
    assert result.files_with_matches == ["a.py"]
    assert result.counts == {"a.py": 1}
    assert {c.line_number for c in result.contexts} == {9, 11}


def test_parse_rg_json_decodes_base64_bytes_paths() -> None:
    import base64

    blob = base64.b64encode("ファイル.py".encode()).decode("ascii")
    events = [
        {"type": "begin", "data": {"path": {"bytes": blob}}},
        {
            "type": "match",
            "data": {
                "path": {"bytes": blob},
                "lines": {"text": "hit\n"},
                "line_number": 1,
            },
        },
        {"type": "end", "data": {"path": {"bytes": blob}, "stats": {"matches": 1}}},
    ]
    stdout = "\n".join(json.dumps(e) for e in events).encode("utf-8")
    result = parse_rg_json(stdout)
    assert result.matches[0].file_path == "ファイル.py"
    assert result.counts == {"ファイル.py": 1}
