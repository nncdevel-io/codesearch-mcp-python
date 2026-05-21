"""Shared pytest fixtures and skip markers."""

from __future__ import annotations

import shutil

import pytest


def _binary_available(name: str) -> bool:
    return shutil.which(name) is not None


requires_git = pytest.mark.skipif(not _binary_available("git"), reason="git binary not available")
requires_rg = pytest.mark.skipif(
    not _binary_available("rg"), reason="ripgrep (rg) binary not available"
)
