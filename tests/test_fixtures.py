"""Smoke tests for the bare-git fixture helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .conftest import requires_git
from .fixtures import init_bare, init_working_tree, make_remote_with_files


@requires_git
def test_init_bare_creates_bare_repository(tmp_path: Path) -> None:
    bare = init_bare(tmp_path / "bare.git")
    out = subprocess.run(
        ["git", "-C", str(bare.path), "rev-parse", "--is-bare-repository"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == "true"


@requires_git
def test_make_remote_with_files_round_trips(tmp_path: Path) -> None:
    bare = make_remote_with_files(
        tmp_path / "bare.git",
        tmp_path / "work",
        {"src/a.py": "print('a')\n", "README.md": "# hi\n"},
    )
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", bare.url, str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (clone / "src" / "a.py").read_text() == "print('a')\n"
    assert (clone / "README.md").read_text() == "# hi\n"


@requires_git
def test_init_working_tree_commits_files(tmp_path: Path) -> None:
    init_working_tree(tmp_path / "wt", {"x.txt": "hello"})
    log = subprocess.run(
        ["git", "-C", str(tmp_path / "wt"), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "initial" in log.stdout
