"""Spec ↔ implementation alignment for tool input schemas (harness report §4.6).

The four MCP tool input schemas are declared in ``docs/spec/spec.md`` (§4.1 –
§4.4). They are also expressed in code via Pydantic models in
``codesearch_mcp/tools/schemas.py``. Both must agree on required fields, types,
enum ranges, and min/max bounds — otherwise the server lies to its clients.

We parse the JSON Schema fragments out of the spec markdown and compare each
key constraint against the Pydantic-derived JSON Schema for the same tool.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from codesearch_mcp.tools.schemas import (
    ListFilesInput,
    ListRepositoriesInput,
    ListTreeInput,
    ReadFileInput,
    SearchCodeInput,
)

SPEC = Path(__file__).resolve().parent.parent / "docs" / "spec" / "spec.md"


def _read_spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _extract_input_schemas(text: str) -> dict[str, dict]:
    """Pull `inputSchema` JSON blocks for each tool out of spec.md.

    Returns a mapping tool_name -> parsed JSON object.
    """

    # The spec uses headers like "### 4.1 search_code" and "#### 4.1.1 inputSchema".
    schemas: dict[str, dict] = {}
    # Find tool sections by header.
    sections = re.split(r"^### (4\.\d) ([a-z_]+)\s*$", text, flags=re.MULTILINE)
    # sections layout: [pre, "4.1", "search_code", body, "4.2", "list_files", body, ...]
    for idx in range(1, len(sections), 3):
        tool = sections[idx + 1]
        body = sections[idx + 2]
        m = re.search(
            r"####\s+\d+\.\d+\.\d+\s+inputSchema\s*\n+```json\n(.*?)\n```",
            body,
            flags=re.DOTALL,
        )
        if m:
            schemas[tool] = json.loads(m.group(1))
    return schemas


TOOL_MODEL_MAP = {
    "search_code": SearchCodeInput,
    "list_files": ListFilesInput,
    "list_tree": ListTreeInput,
    "read_file": ReadFileInput,
    "list_repositories": ListRepositoriesInput,
}


@pytest.fixture(scope="module")
def spec_schemas() -> dict[str, dict]:
    schemas = _extract_input_schemas(_read_spec_text())
    missing = set(TOOL_MODEL_MAP) - set(schemas)
    if missing:
        pytest.fail(f"spec.md inputSchema sections missing for: {sorted(missing)}")
    return schemas


def _impl_schema(name: str) -> dict:
    model = TOOL_MODEL_MAP[name]
    return model.model_json_schema()


def test_all_four_tools_present(spec_schemas: dict[str, dict]) -> None:
    assert set(spec_schemas) == set(TOOL_MODEL_MAP)


@pytest.mark.parametrize("tool", sorted(TOOL_MODEL_MAP))
def test_required_fields_match_spec(tool: str, spec_schemas: dict[str, dict]) -> None:
    spec_required = set(spec_schemas[tool].get("required", []))
    impl_required = set(_impl_schema(tool).get("required", []))
    assert impl_required == spec_required, (
        f"{tool} required mismatch: spec={spec_required} impl={impl_required}"
    )


@pytest.mark.parametrize("tool", sorted(TOOL_MODEL_MAP))
def test_property_keys_match_spec(tool: str, spec_schemas: dict[str, dict]) -> None:
    spec_props = set(spec_schemas[tool]["properties"].keys())
    impl_props = set(_impl_schema(tool)["properties"].keys())
    assert impl_props == spec_props, (
        f"{tool} property keys mismatch: spec={spec_props} impl={impl_props}"
    )


def _lookup_constraint(impl_def: dict, key: str) -> object:
    """Pydantic represents ``Optional[T]`` as ``anyOf: [{...constraint}, {type: null}]``;
    bounds live inside the non-null branch."""

    if key in impl_def:
        return impl_def[key]
    for branch in impl_def.get("anyOf", []):
        if isinstance(branch, dict) and branch.get("type") != "null" and key in branch:
            return branch[key]
    return None


@pytest.mark.parametrize("tool", sorted(TOOL_MODEL_MAP))
def test_numeric_bounds_match_spec(tool: str, spec_schemas: dict[str, dict]) -> None:
    spec_props = spec_schemas[tool]["properties"]
    impl_props = _impl_schema(tool)["properties"]
    for name, spec_def in spec_props.items():
        for bound in ("minimum", "maximum", "minLength", "maxLength"):
            if bound in spec_def:
                actual = _lookup_constraint(impl_props[name], bound)
                assert actual == spec_def[bound], (
                    f"{tool}.{name} {bound} mismatch: spec={spec_def[bound]} impl={actual}"
                )


@pytest.mark.parametrize("tool", sorted(TOOL_MODEL_MAP))
def test_defaults_match_spec(tool: str, spec_schemas: dict[str, dict]) -> None:
    spec_props = spec_schemas[tool]["properties"]
    impl_props = _impl_schema(tool)["properties"]
    for name, spec_def in spec_props.items():
        if "default" in spec_def:
            assert impl_props[name].get("default") == spec_def["default"], (
                f"{tool}.{name} default mismatch: "
                f"spec={spec_def['default']} impl={impl_props[name].get('default')}"
            )


@pytest.mark.parametrize("tool", sorted(TOOL_MODEL_MAP))
def test_enum_values_match_spec(tool: str, spec_schemas: dict[str, dict]) -> None:
    spec_props = spec_schemas[tool]["properties"]
    impl_props = _impl_schema(tool)["properties"]
    for name, spec_def in spec_props.items():
        if "enum" in spec_def:
            # Pydantic with Literal renders as "enum" too.
            assert set(impl_props[name].get("enum", [])) == set(spec_def["enum"]), (
                f"{tool}.{name} enum mismatch"
            )


@pytest.mark.parametrize("tool", sorted(TOOL_MODEL_MAP))
def test_additional_properties_disallowed(tool: str, spec_schemas: dict[str, dict]) -> None:
    # Spec explicitly sets `additionalProperties: false` for every tool.
    assert spec_schemas[tool].get("additionalProperties") is False
    assert _impl_schema(tool).get("additionalProperties") is False
