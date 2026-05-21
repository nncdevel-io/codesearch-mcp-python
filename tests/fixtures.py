"""Helpers for building bare-git remotes and working repositories in tests."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BareRemote:
    """A local bare repository acting as a Git 'remote' for tests."""

    path: Path

    @property
    def url(self) -> str:
        return str(self.path)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )


def init_bare(path: Path) -> BareRemote:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "--bare", "--initial-branch=main", str(path)])
    return BareRemote(path=path)


def init_working_tree(path: Path, files: dict[str, str]) -> None:
    """Initialise a working tree at ``path`` with the given files (relative paths)."""

    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "--initial-branch=main", str(path)])
    _run(["git", "config", "user.email", "test@example.invalid"], cwd=path)
    _run(["git", "config", "user.name", "Test"], cwd=path)
    _run(["git", "config", "commit.gpgsign", "false"], cwd=path)
    for rel, contents in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    _run(["git", "add", "-A"], cwd=path)
    _run(["git", "commit", "-m", "initial"], cwd=path)


def push_to_bare(working: Path, bare: BareRemote, branch: str = "main") -> None:
    _run(["git", "remote", "remove", "origin"], cwd=working) if (
        working / ".git" / "config"
    ).read_text().find('[remote "origin"]') != -1 else None
    _run(["git", "remote", "add", "origin", bare.url], cwd=working)
    _run(["git", "push", "-u", "origin", branch], cwd=working)


def make_remote_with_files(
    bare_path: Path,
    work_path: Path,
    files: dict[str, str],
    branch: str = "main",
) -> BareRemote:
    bare = init_bare(bare_path)
    init_working_tree(work_path, files)
    if branch != "main":
        _run(["git", "branch", "-M", branch], cwd=work_path)
    _run(["git", "remote", "add", "origin", bare.url], cwd=work_path)
    _run(["git", "push", "-u", "origin", branch], cwd=work_path)
    return bare


def append_commit(work_path: Path, rel: str, contents: str, message: str) -> None:
    target = work_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents)
    _run(["git", "add", rel], cwd=work_path)
    _run(["git", "commit", "-m", message], cwd=work_path)
    _run(["git", "push"], cwd=work_path)


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def files_in(path: Path) -> Iterable[str]:
    for p in sorted(path.rglob("*")):
        if p.is_file():
            yield str(p.relative_to(path))
