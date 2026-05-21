"""Pydantic input-schema validators (``tools/schemas.py``)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codesearch_mcp.tools.schemas import (
    ListFilesInput,
    ListTreeInput,
    ReadFileInput,
    SearchCodeInput,
)


@pytest.mark.parametrize(
    "model",
    [SearchCodeInput, ListFilesInput, ListTreeInput, ReadFileInput],
)
@pytest.mark.parametrize(
    "bad_repo",
    ["has space", "slash/in/name", "tab\tname", "unicode名前", "with$dollar"],
)
def test_repository_field_rejects_invalid_id(model: type, bad_repo: str) -> None:
    """``_validate_repo_id`` enforces ``^[a-zA-Z0-9._-]+$``; anything else
    must raise a Pydantic ``ValidationError`` whose message mentions the
    pattern."""

    base: dict[str, object] = {"repository": bad_repo}
    if model is SearchCodeInput:
        base["pattern"] = "needle"
    elif model is ListFilesInput:
        base["pattern"] = "*.py"
    elif model is ReadFileInput:
        base["file_path"] = "src/main.py"

    with pytest.raises(ValidationError) as ei:
        model.model_validate(base)
    assert "^[a-zA-Z0-9._-]+$" in str(ei.value)
