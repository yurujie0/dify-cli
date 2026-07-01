from __future__ import annotations

import json
from typing import Any

from . import graph as graph_mod
from .errors import NodeValidationError
from .schema_store import get_node_schema

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


def _apply_array_defaults(data: dict[str, Any], schema: dict[str, Any]) -> None:
    """Fill empty arrays for optional array fields the frontend expects present."""
    props = schema.get("properties", {})
    for name, sub in props.items():
        if name in data:
            continue
        if sub.get("type") == "array":
            data[name] = []


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
    data: dict[str, Any] = {"type": node_type}
    if title:
        data["title"] = title
    data.setdefault("desc", "")
    data.setdefault("selected", False)
    if fields:
        apply_fields(data, fields)
    _apply_array_defaults(data, schema)
    validate_node_data(node_type, data, schema)
    pos = position or {"x": 0.0, "y": 0.0}
    return {
        "id": node_id or graph_mod.new_node_id(node_type),
        "type": "custom",
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
