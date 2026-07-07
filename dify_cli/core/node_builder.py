from __future__ import annotations

import copy
import json
from typing import Any

from . import graph as graph_mod
from .errors import NodeValidationError
from .schema_store import get_node_defaults, get_node_schema

_SENTINEL = object()


def _set_dotted(target: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cur = target
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def parse_field_value(raw: str) -> Any:
    if raw is None:
        return None
    # @filename: read value from a file (handles multi-line code, etc.)
    # @- reads from stdin.
    if raw.startswith("@"):
        target = raw[1:]
        if target == "-":
            import sys
            return sys.stdin.read()
        from pathlib import Path
        p = Path(target)
        if not p.exists():
            raise NodeValidationError("", f"Field value file not found: {target}")
        return p.read_text(encoding="utf-8")
    s = raw.strip()
    if s and s[0] in "{[":
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    return raw


def apply_fields(target: dict[str, Any], fields: list[str]) -> None:
    for f in fields:
        if "=" not in f:
            raise NodeValidationError("", f"Invalid --field {f!r}; expected key=value")
        key, _, raw = f.partition("=")
        _set_dotted(target, key.strip(), parse_field_value(raw))


_DEFAULT_NODE_WIDTH = 244
_DEFAULT_NODE_HEIGHT = 90

# Iteration/loop start nodes use a dedicated ReactFlow renderer
# (custom-iteration-start / custom-loop-start), not the generic "custom".
# The frontend looks up the renderer by the top-level `type` field and
# crashes if it's "custom" for these node types.
_REACTFLOW_TYPE_OVERRIDES = {
    "iteration-start": "custom-iteration-start",
    "loop-start": "custom-loop-start",
}


def _post_process(node_type: str, data: dict[str, Any]) -> None:
    """Fill in runtime fields the frontend generates on user interaction but
    the backend schema doesn't require.

    When a user clicks "add condition" / "add variable" in the UI, the
    frontend's use-config.ts generates id (React key), varType (UI rendering),
    groupId, etc. via uuid4(). Static extraction from default.ts cannot capture
    these — they're created in event handlers, not in defaultValue.

    Rather than special-case each node type, we walk the data tree and patch
    any object that looks like a frontend-generated child element (condition,
    loop variable, group) with the missing runtime fields. The shape rules are
    distilled from use-config.ts handleAddXxx handlers across nodes.
    """
    _walk_and_patch(data)


def _walk_and_patch(obj: Any) -> None:
    """Recursively patch runtime-generated fields on child elements.

    Rules (from frontend use-config.ts handlers):
    - Condition object (has variable_selector + comparison_operator): needs id + varType
    - Metadata condition (has name + comparison_operator, no variable_selector): needs id
    - Loop variable (has var_type): needs id
    - Group (has groupId): groupId is its own id field, leave as-is
    - Any object with varType but no id: needs id
    """
    import uuid

    if isinstance(obj, dict):
        is_condition = "variable_selector" in obj and "comparison_operator" in obj
        is_metadata_condition = (
            "name" in obj and "comparison_operator" in obj and "variable_selector" not in obj
        )
        is_loop_variable = "var_type" in obj

        if is_condition or is_metadata_condition or is_loop_variable or "varType" in obj:
            obj.setdefault("id", uuid.uuid4().hex)
            if is_condition:
                obj.setdefault("varType", "string")

        for v in obj.values():
            _walk_and_patch(v)
    elif isinstance(obj, list):
        for item in obj:
            _walk_and_patch(item)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base; overlay wins on conflicts."""
    result: dict[str, Any] = copy.deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def build_node(
    *,
    node_type: str,
    dsl_version: str,
    node_id: str | None = None,
    title: str | None = None,
    fields: list[str] | None = None,
    position: dict[str, float] | None = None,
) -> dict[str, Any]:
    schema = get_node_schema(dsl_version, node_type)

    # Start from the frontend's defaultValue template (the exact `data` the UI
    # uses when creating a node). This guarantees the resulting DSL matches
    # what the UI produces and imports cleanly.
    frontend_defaults = get_node_defaults(dsl_version, node_type)
    data: dict[str, Any] = copy.deepcopy(frontend_defaults) if frontend_defaults else {}
    data["type"] = node_type
    if title is not None:
        data["title"] = title
    data.setdefault("desc", "")
    data.setdefault("selected", False)

    if fields:
        user_overlay: dict[str, Any] = {}
        apply_fields(user_overlay, fields)
        data = _deep_merge(data, user_overlay)

    _post_process(node_type, data)
    validate_node_data(node_type, data, schema)
    pos = position or {"x": 0.0, "y": 0.0}
    return {
        "id": node_id or graph_mod.new_node_id(node_type),
        "type": _REACTFLOW_TYPE_OVERRIDES.get(node_type, "custom"),
        "data": data,
        "position": pos,
        "positionAbsolute": {"x": pos["x"], "y": pos["y"]},
        "width": _DEFAULT_NODE_WIDTH,
        "height": _DEFAULT_NODE_HEIGHT,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
    }


def validate_node_data(node_type: str, data: dict[str, Any], schema: dict) -> None:
    import jsonschema

    validator = jsonschema.Draft7Validator(schema)
    errs = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errs:
        e = errs[0]
        path = ".".join(str(p) for p in e.absolute_path) or None
        raise NodeValidationError(node_type, e.message, path)
