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
    # Template variables like {{#node.var#}} start with {{ - NOT JSON. Treat as
    # plain string. (A real JSON object starts with {" or {space, not {{.)
    if s and s[0] in "{[" and not s.startswith("{{"):
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            # Surface the JSON error clearly. Common causes:
            # - missing quotes around strings: [123,foo] instead of ["123","foo"]
            # - Windows shell stripped double quotes from --field '...["x","y"]...'
            raise NodeValidationError(
                "",
                f"value looks like JSON (starts with {s[0]!r}) but failed to parse: {e.msg}. "
                f"This is often a Windows shell quoting issue (double quotes get stripped). "
                f"Use --fields-file to pass JSON values portably across platforms.",
            )
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

# Container nodes are larger than regular nodes (matches frontend defaults).
_NODE_DIMENSIONS = {
    "iteration": (388, 178),
    "loop": (388, 178),
    "iteration-start": (44, 48),
    "loop-start": (44, 48),
}


# Common agent mistakes that can be auto-corrected before validation.
# Maps node_type -> {field: {bad_value: good_value}}.
_FIELD_NORMALIZERS = {
    "code": {
        "code_language": {"python": "python3", "py": "python3", "js": "javascript"},
    },
}


def _post_process(node_type: str, data: dict[str, Any]) -> None:
    """Fill in runtime fields the frontend generates on user interaction but
    the backend schema doesn't require.

    When a user clicks "add condition" / "add variable" in the UI, the
    frontend's use-config.ts generates id (React key), varType (UI rendering),
    groupId, etc. via uuid4(). Static extraction from default.ts cannot capture
    these - they're created in event handlers, not in defaultValue.

    Rather than special-case each node type, we walk the data tree and patch
    any object that looks like a frontend-generated child element (condition,
    loop variable, group) with the missing runtime fields. The shape rules are
    distilled from use-config.ts handleAddXxx handlers across nodes.
    """
    _normalize_fields(node_type, data)
    _walk_and_patch(data)


def _normalize_fields(node_type: str, data: dict[str, Any]) -> None:
    """Auto-correct common agent mistakes before schema validation rejects them.

    Example: code.code_language='python' -> 'python3' (schema enum is
    ['python3','javascript'], agents often write 'python').
    """
    rules = _FIELD_NORMALIZERS.get(node_type, {})
    for field, mapping in rules.items():
        if field in data and data[field] in mapping:
            data[field] = mapping[data[field]]


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
    fields_dict: dict[str, Any] | None = None,
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

    if fields_dict:
        data = _deep_merge(data, fields_dict)
    elif fields:
        user_overlay: dict[str, Any] = {}
        apply_fields(user_overlay, fields)
        data = _deep_merge(data, user_overlay)

    _post_process(node_type, data)
    validate_node_data(node_type, data, schema)
    pos = position or {"x": 0.0, "y": 0.0}
    width, height = _NODE_DIMENSIONS.get(node_type, (_DEFAULT_NODE_WIDTH, _DEFAULT_NODE_HEIGHT))
    return {
        "id": node_id or graph_mod.new_node_id(node_type),
        "type": _REACTFLOW_TYPE_OVERRIDES.get(node_type, "custom"),
        "data": data,
        "position": pos,
        "positionAbsolute": {"x": pos["x"], "y": pos["y"]},
        "width": width,
        "height": height,
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


def fields_dict_to_list(fields_dict: dict[str, Any]) -> list[str]:
    """Convert a fields dict (as used in --fields-file / apply spec) to the
    `["k=v", ...]` list form consumed by apply_fields / build_node.

    dict/list values are JSON-serialized; string values are kept as-is (so
    `@file` references pass through to parse_field_value); other scalars
    are stringified.
    """
    out: list[str] = []
    for k, v in fields_dict.items():
        if isinstance(v, (dict, list)):
            out.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
        elif isinstance(v, bool):
            out.append(f"{k}={'true' if v else 'false'}")
        elif v is None:
            out.append(f"{k}=null")
        else:
            out.append(f"{k}={v}")
    return out


def attach_to_parent(node: dict[str, Any], parent_id: str, parent_type: str) -> None:
    """Mark a node as a child of an iteration/loop container so ReactFlow
    renders it inside the container. Mirrors frontend getIterationStartNode
    child placement.
    """
    node["parentId"] = parent_id
    node["zIndex"] = 1002  # ITERATION/LOOP_CHILDREN_Z_INDEX
    node["extent"] = "parent"
    node["position"] = {"x": 128, "y": 68}
    node["positionAbsolute"] = {"x": 128, "y": 68}
    if parent_type == "iteration":
        node["data"]["isInIteration"] = True
        node["data"]["iteration_id"] = parent_id
    else:
        node["data"]["isInLoop"] = True
        node["data"]["loop_id"] = parent_id


def create_container_start(parent_node: dict[str, Any], parent_type: str, dsl_version: str) -> dict[str, Any]:
    """Create the auto iteration-start / loop-start child node for a container
    node, link parent.start_node_id, and set the parent's container zIndex.
    Mirrors web/app/components/workflow/utils/node.ts:getIterationStartNode.
    """
    start_type = "iteration-start" if parent_type == "iteration" else "loop-start"
    start_node = build_node(
        node_type=start_type,
        dsl_version=dsl_version,
        title="",
        fields=None,
        position={"x": 24, "y": 68},
    )
    start_node["id"] = graph_mod.new_iteration_start_id(parent_node["id"])
    start_node["parentId"] = parent_node["id"]
    start_node["zIndex"] = 1002  # ITERATION/LOOP_CHILDREN_Z_INDEX
    start_node["selectable"] = False
    start_node["draggable"] = False
    start_node["data"]["isInIteration"] = parent_type == "iteration"
    start_node["data"]["isInLoop"] = parent_type == "loop"
    parent_node["data"]["start_node_id"] = start_node["id"]
    parent_node["zIndex"] = 1  # ITERATION/LOOP_NODE_Z_INDEX
    return start_node
