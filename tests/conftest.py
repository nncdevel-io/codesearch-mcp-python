"""Shared pytest fixtures and skip markers."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator

import pytest


def _binary_available(name: str) -> bool:
    return shutil.which(name) is not None


requires_git = pytest.mark.skipif(not _binary_available("git"), reason="git binary not available")
requires_rg = pytest.mark.skipif(
    not _binary_available("rg"), reason="ripgrep (rg) binary not available"
)


@pytest.fixture(autouse=True)
def _restore_codesearch_logger_propagation() -> Iterator[None]:
    """Force ``codesearch_mcp`` logger propagation on for every test.

    ``configure_logging`` (called by some tests) sets ``propagate=False`` to
    avoid double-handling in production. That suppresses ``caplog`` capture
    in any *subsequent* test, since caplog hooks the root logger. Resetting
    to ``True`` before each test keeps caplog-based assertions reliable
    regardless of execution order.
    """
    logger = logging.getLogger("codesearch_mcp")
    saved = logger.propagate
    logger.propagate = True
    try:
        yield
    finally:
        logger.propagate = saved
