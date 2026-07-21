"""Spec semantic validator: checks variable references and scope.

The spec format encodes workflow structure, but variable references
(value_selector / variable_selector) are only valid if they point to a
variable the target node actually exposes, AND the target is in scope
(e.g. can't reference a node inside an iteration/loop container from
outside it). The schema can't express these semantic rules - this
validator encodes them as the single source of truth for variable
semantics, used by `dify-cli spec validate` and defensively by `apply`.
"""
from __future__ import annotations

from typing import Any, Iterator

# Node types where we don't know the exposed variables statically (depend on
# runtime / external config). For these we only check the target node exists
# and is in scope, not the specific variable name.
_LOOSE_TYPES = {"tool", "agent"}

# Fields that contain a single selector ([node_id, var]). Keyed by node type.
# A selector is a 2+ element list where [0] is the node id and [1] is the var.
_SELECTOR_FIELDS = {
    "code": ["variables.*.value_selector"],
    "end": ["outputs.*.value_selector"],
    "template-transform": ["variables.*.value_selector"],
    "llm": ["context.variable_selector"],
    "if-else": ["cases.*.conditions.*.variable_selector"],
    "iteration": ["iterator_selector", "output_selector"],
    "loop": ["break_conditions.*.variable_selector", "loop_variables.*.value_selector"],
    "knowledge-retrieval": ["query_variable_selector"],
    "question-classifier": ["query_variable_selector"],
}

# Fields that contain a list of selectors (array of arrays), e.g.
# variable-aggregator.variables = [[node_id, var], ...]
_SELECTOR_LIST_FIELDS = {
    "variable-aggregator": ["variables"],
}


def validate_spec(spec: dict[str, Any]) -> list[str]:
    """Validate a spec's structure at design stage: node types, IO variable
    references, edges, and scope. Does NOT read @file (internal config) -
    that's filled at implementation stage and checked by `node check` / apply.

    Returns a list of human-readable error strings (empty = valid)."""
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    nodes = spec.get("nodes", [])
    if not isinstance(nodes, list):
        return ["spec.nodes must be a list"]

    # Flatten nodes (including iteration/loop children) with their parentId.
    flat: list[dict[str, Any]] = []
    for n in nodes:
        flat.append(n)
        if n.get("type") in ("iteration", "loop"):
            for child in n.get("children", []):
                child["_parentId"] = n["id"]
                flat.append(child)
    nodes_by_id = {n["id"]: n for n in flat}

    errors: list[str] = []
    for node in flat:
        for path, selector in _extract_references(node):
            errors.extend(_check_reference(node, path, selector, nodes_by_id))

    errors.extend(_check_variables(spec))
    errors.extend(_check_node_ids(spec))
    return errors


# Valid value_type for environment/conversation variables (SegmentType subset).
# Agents sometimes write "text" (a start variable type) instead of "string".
_VALID_VAR_VALUE_TYPES = {
    "string", "number", "integer", "float", "object", "secret",
    "boolean", "array[any]", "array[string]", "array[number]",
    "array[object]", "array[boolean]", "array[file]", "file", "none",
}


def _check_variables(spec: dict[str, Any]) -> list[str]:
    """Check environment/conversation variable value_type is valid."""
    errors: list[str] = []
    for ev in spec.get("environment_variables", []) or []:
        vt = ev.get("value_type", "string")
        if vt not in _VALID_VAR_VALUE_TYPES:
            errors.append(
                f"environment_variable {ev.get('name', '?')!r}: value_type {vt!r} is not valid. "
                f"Use 'string' (not 'text'). Valid: {sorted(_VALID_VAR_VALUE_TYPES)}"
            )
    for cv in spec.get("conversation_variables", []) or []:
        vt = cv.get("value_type", "string")
        if vt not in _VALID_VAR_VALUE_TYPES:
            errors.append(
                f"conversation_variable {cv.get('name', '?')!r}: value_type {vt!r} is not valid. "
                f"Use 'string' (not 'text'). Valid: {sorted(_VALID_VAR_VALUE_TYPES)}"
            )
    return errors


def _check_node_ids(spec: dict[str, Any]) -> list[str]:
    """Check node ids are path-safe ([a-z0-9_-]+) - they're used directly as
    impl filenames. Also catches duplicate ids."""
    from .spec_format import is_valid_node_id
    errors: list[str] = []
    seen: set[str] = set()

    def _check(nid: str, ntype: str) -> None:
        if not is_valid_node_id(nid):
            errors.append(
                f"node id {nid!r} ({ntype}): must match [a-z0-9_-]+ "
                f"(used as impl filename). Use lowercase, no spaces/slashes."
            )
        elif nid in seen:
            errors.append(f"duplicate node id {nid!r}")
        else:
            seen.add(nid)

    for n in spec.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        _check(n.get("id", ""), n.get("type", ""))
        for child in n.get("children", []) or []:
            if isinstance(child, dict):
                _check(child.get("id", ""), child.get("type", ""))
    return errors


# Fields where a container node legitimately references its own child(ren).
# Only these allow the container->child reference path.
_CONTAINER_CHILD_FIELDS = {"output_selector"}


def _extract_references(node: dict[str, Any]) -> Iterator[tuple[str, list]]:
    """Yield (field_path, selector) pairs from a spec node's hoisted top-level
    fields. Does NOT read `fields` (@file) - selectors live at the spec layer."""
    ntype = node.get("type", "")

    for pattern in _SELECTOR_FIELDS.get(ntype, []):
        for path, value in _walk_pattern(node, pattern):
            if isinstance(value, list) and len(value) >= 2:
                yield (path, value)

    for pattern in _SELECTOR_LIST_FIELDS.get(ntype, []):
        for path, value in _walk_pattern(node, pattern):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, list) and len(item) >= 2:
                        yield (path, item)


def _walk_pattern(data: Any, pattern: str) -> Iterator[tuple[str, Any]]:
    """Walk data following a dotted pattern with '*' wildcards for list items.
    e.g. 'cases.*.conditions.*.variable_selector' yields each leaf."""
    parts = pattern.split(".")
    yield from _walk_parts(data, parts, "")


def _walk_parts(data: Any, parts: list[str], path: str) -> Iterator[tuple[str, Any]]:
    if not parts:
        yield (path, data)
        return
    part, rest = parts[0], parts[1:]
    if part == "*":
        if isinstance(data, list):
            for i, item in enumerate(data):
                yield from _walk_parts(item, rest, f"{path}[{i}]")
    else:
        if isinstance(data, dict) and part in data:
            yield from _walk_parts(data[part], rest, f"{path}.{part}" if path else part)


def _walk_all_strings(data: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(data, str):
        yield (path, data)
    elif isinstance(data, dict):
        for k, v in data.items():
            yield from _walk_all_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from _walk_all_strings(v, f"{path}[{i}]")


def _extract_template_refs(text: str) -> Iterator[tuple[str, str]]:
    """Extract {{#node_id.var#}} references from a template string."""
    import re
    for m in re.finditer(r"\{\{#([\w-]+)\.(\w+)#\}\}", text):
        yield (m.group(1), m.group(2))


def _check_reference(
    node: dict[str, Any], path: str, selector: list, nodes_by_id: dict
) -> list[str]:
    target_id = selector[0]
    var = selector[1] if len(selector) > 1 else ""
    nid = node.get("id", "?")
    full = f"{nid}.fields.{path}" if path else f"{nid}.fields"

    target = nodes_by_id.get(target_id)
    if target is None:
        return [f"{full}: references node {target_id!r} which does not exist"]

    if not _in_scope(target, node, path):
        container = target.get("_parentId") or target.get("parentId")
        return [
            f"{full}: cannot reference {target_id!r} from here - it is inside "
            f"container {container!r}. Reference the container node instead."
        ]

    if target.get("type") in _LOOSE_TYPES:
        return []

    exposed = _exposed_vars(target, node)
    if var not in exposed:
        return [
            f"{full}: node {target_id!r} ({target.get('type')}) does not expose "
            f"variable {var!r}. Exposes: {sorted(exposed) or '(none)'}."
        ]
    return []


def _in_scope(target: dict, ref: dict, path: str = "") -> bool:
    """A target node is visible to the referencing node if:
    - the target is top-level, or
    - both are in the same container (siblings), or
    - the ref IS the target's container AND the field is one that
      legitimately points into the container's own subgraph (e.g.
      iteration.output_selector naming the inner node to collect)."""
    target_parent = target.get("_parentId") or target.get("parentId")
    ref_id = ref.get("id")
    if target_parent is None:
        return True
    if target_parent == ref_id:
        # container referencing its own child - only allowed for fields
        # that legitimately point into the subgraph (output_selector).
        leaf = path.split(".")[-1] if path else ""
        return leaf in _CONTAINER_CHILD_FIELDS
    ref_parent = ref.get("_parentId") or ref.get("parentId")
    return target_parent == ref_parent


def _exposed_vars(target: dict, ref: dict) -> set[str]:
    """Variables a target node exposes to the referencing node. For containers
    (iteration/loop), depends on whether ref is inside the target. Reads IO
    declarations from the spec node top-level (hoisted fields), not @file."""
    ttype = target.get("type", "")
    ref_inside_target = (ref.get("_parentId") or ref.get("parentId")) == target.get("id")

    if ttype == "start":
        return {v.get("variable", "") for v in target.get("variables", []) if isinstance(v, dict)}
    if ttype == "code":
        outs = target.get("outputs", {})
        return set(outs.keys()) if isinstance(outs, dict) else set()
    if ttype == "llm":
        return {"text"}  # structured_output is in @file, not checked at design stage
    if ttype == "http-request":
        return {"body", "headers", "status_code", "files"}
    if ttype in ("template-transform", "variable-aggregator", "list-operator"):
        return {"output"}
    if ttype == "iteration":
        return {"item", "index"} if ref_inside_target else {"output"}
    if ttype == "loop":
        lvs = target.get("loop_variables", [])
        return {lv.get("label", "") for lv in lvs if isinstance(lv, dict)}
    if ttype == "knowledge-retrieval":
        return {"result"}
    if ttype == "question-classifier":
        return {"class_name"}
    if ttype == "parameter-extractor":
        params = target.get("parameters", [])
        return {p.get("name", "") for p in params if isinstance(p, dict)}
    if ttype == "document-extractor":
        return {"text", "result"}
    if ttype in ("end", "answer"):
        return set()
    return set()
