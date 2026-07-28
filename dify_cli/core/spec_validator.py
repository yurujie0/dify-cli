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

    # Build node index and assign parentId to children (children are now
    # top-level, referenced by id in the parent's `children` list).
    nodes_by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if n.get("type") in ("iteration", "loop"):
            for child_id in n.get("children", []):
                child = nodes_by_id.get(child_id)
                if child is not None:
                    child["_parentId"] = n["id"]

    errors: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for path, selector in _extract_references(node):
            errors.extend(_check_reference(node, path, selector, nodes_by_id, spec))
    errors.extend(_check_selector_format(spec))
    errors.extend(_check_template_inputs_format(spec))

    errors.extend(_check_variables(spec))
    errors.extend(_check_node_ids(spec))
    errors.extend(_check_edges(spec, nodes_by_id))
    errors.extend(_check_hoisted_structure(spec))
    errors.extend(_check_mode_node_compat(spec))
    errors.extend(_check_edge_coverage(spec, nodes_by_id))
    errors.extend(_check_schema_for_complete_nodes(spec, nodes_by_id))
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


# All selector field patterns (value_selector + variable_selector + iterators etc.)
_ALL_SELECTOR_PATTERNS = {
    "code": ["variables.*.value_selector"],
    "end": ["outputs.*.value_selector"],
    "template-transform": ["variables.*.value_selector"],
    "llm": [],
    "if-else": ["cases.*.conditions.*.variable_selector"],
    "iteration": ["iterator_selector", "output_selector"],
    "loop": ["break_conditions.*.variable_selector"],
    "variable-aggregator": ["variables"],
    "knowledge-retrieval": ["query_variable_selector"],
    "question-classifier": ["query_variable_selector"],
    "parameter-extractor": ["query"],
    "document-extractor": ["variable_selector"],
}


def _check_selector_format(spec: dict[str, Any]) -> list[str]:
    """Check that all value_selector/variable_selector are 2+ element string
    arrays (['node_id', 'var']), not single-element dotted strings like
    ['sys.env.XXX'] or ['env.XXX']."""
    errors: list[str] = []
    for n in spec.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        nid = n.get("id", "?")
        ntype = n.get("type", "")
        for pattern in _ALL_SELECTOR_PATTERNS.get(ntype, []):
            for path, value in _walk_pattern(n, pattern):
                if not isinstance(value, list):
                    continue
                # variable-aggregator.variables is array of arrays
                if ntype == "variable-aggregator":
                    for item in value:
                        _check_one_selector(item, nid, path, errors)
                else:
                    _check_one_selector(value, nid, path, errors)
    return errors


def _check_template_inputs_format(spec: dict[str, Any]) -> list[str]:
    """Check that template_inputs is a list of 2+ element string arrays."""
    errors: list[str] = []
    for n in spec.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        nid = n.get("id", "?")
        ti = n.get("template_inputs")
        if ti is None:
            continue
        if not isinstance(ti, list):
            errors.append(f"node {nid!r}: template_inputs must be a list, got {type(ti).__name__}")
            continue
        for i, item in enumerate(ti):
            if not isinstance(item, list):
                errors.append(
                    f"node {nid!r}: template_inputs[{i}] must be an array like "
                    f"[\"node_id\",\"var\"], got {type(item).__name__} {item!r}. "
                    f"Do NOT use object format."
                )
                continue
            _check_one_selector(item, nid, f"template_inputs[{i}]", errors)
    return errors


def _check_one_selector(selector: Any, nid: str, path: str, errors: list[str]) -> None:
    """Validate a single selector: must be 2+ element array of strings."""
    if not isinstance(selector, list):
        return
    if len(selector) < 2:
        # Likely ['sys.env.XXX'] or ['env.XXX'] - agent used dotted string
        errors.append(
            f"node {nid!r}: {path}: selector must be a 2+ element array like "
            f"['node_id','var'], got {selector!r} (single-element). "
            f"For env vars use ['env','VAR_NAME'], not ['env.VAR_NAME']."
        )
        return
    for elem in selector:
        if not isinstance(elem, str):
            errors.append(
                f"node {nid!r}: {path}: selector elements must be strings, "
                f"got {elem!r} in {selector!r}"
            )
            return
    # Check for dotted first element (e.g. ['sys.env.XXX', 'something'])
    if "." in selector[0] and selector[0] not in ("env", "sys", "conversation"):
        errors.append(
            f"node {nid!r}: {path}: selector first element should be a node id "
            f"or 'env'/'sys'/'conversation', not a dotted path {selector[0]!r}. "
            f"Use ['env','VAR_NAME'] for env vars."
        )


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

    # Check that children references point to existing nodes.
    nodes_by_id = {n.get("id"): n for n in spec.get("nodes", []) or [] if isinstance(n, dict)}
    for n in spec.get("nodes", []) or []:
        if not isinstance(n, dict) or n.get("type") not in ("iteration", "loop"):
            continue
        for child_id in n.get("children", []) or []:
            if child_id not in nodes_by_id:
                errors.append(
                    f"node {n.get('id', '?')!r}: child {child_id!r} not found in spec.nodes"
                )
    return errors


# Required keys for hoisted structures (field name mistakes agents make).
_HOISTED_STRUCTURE_CHECKS = {
    "if-else": {
        "field": "cases",
        "item_required": ["case_id", "logical_operator", "conditions"],
        "common_mistakes": {"id": "case_id", "operator": "comparison_operator"},
        "subfield": "conditions",
        "sub_required": ["variable_selector", "comparison_operator"],
        "sub_mistakes": {"operator": "comparison_operator", "variable": "variable_selector"},
    },
    "loop": {
        "field": "break_conditions",
        "item_required": ["variable_selector", "comparison_operator"],
        "common_mistakes": {"operator": "comparison_operator", "variable": "variable_selector"},
    },
}


def _check_hoisted_structure(spec: dict[str, Any]) -> list[str]:
    """Check that hoisted fields have the correct field names.
    Catches common agent mistakes: id vs case_id, operator vs comparison_operator,
    variable vs variable_selector, nested array in variable_selector."""
    errors: list[str] = []
    for n in spec.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        ntype = n.get("type", "")
        nid = n.get("id", "?")
        check = _HOISTED_STRUCTURE_CHECKS.get(ntype)
        if not check:
            continue
        items = n.get(check["field"]) or []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            # Check common mistakes
            for bad, good in check.get("common_mistakes", {}).items():
                if bad in item and good not in item:
                    errors.append(
                        f"node {nid!r} ({ntype}).{check['field']}[{i}]: "
                        f"use {good!r} not {bad!r}"
                    )
            # Check required keys
            for req in check.get("item_required", []):
                if req not in item:
                    errors.append(
                        f"node {nid!r} ({ntype}).{check['field']}[{i}]: "
                        f"missing required field {req!r}"
                    )
            # Check sub-items (e.g. conditions inside cases)
            subfield = check.get("subfield")
            if subfield:
                for j, sub in enumerate(item.get(subfield, []) or []):
                    if not isinstance(sub, dict):
                        continue
                    for bad, good in check.get("sub_mistakes", {}).items():
                        if bad in sub and good not in sub:
                            errors.append(
                                f"node {nid!r} ({ntype}).{check['field']}[{i}].{subfield}[{j}]: "
                                f"use {good!r} not {bad!r}"
                            )
                    for req in check.get("sub_required", []):
                        if req not in sub:
                            errors.append(
                                f"node {nid!r} ({ntype}).{check['field']}[{i}].{subfield}[{j}]: "
                                f"missing required field {req!r}"
                            )
                    # Check variable_selector is a flat array of strings, not nested
                    vs = sub.get("variable_selector")
                    if vs and isinstance(vs, list) and len(vs) > 0 and isinstance(vs[0], list):
                        errors.append(
                            f"node {nid!r} ({ntype}).{check['field']}[{i}].{subfield}[{j}]: "
                            f"variable_selector must be a flat array like ['node_id','var'], "
                            f"got nested array {vs!r}"
                        )
    return errors


# Node types only valid in specific modes (from frontend use-available-nodes-meta-data.ts).
# workflow: has end + trigger nodes, no answer
# advanced-chat: has answer, no end + trigger nodes
_MODE_NODE_RULES = {
    "workflow": {
        "forbidden": {"answer"},
        "reason": "answer node is only for advanced-chat mode (use end node for workflow output)",
    },
    "advanced-chat": {
        "forbidden": {"end", "trigger-webhook", "trigger-schedule", "trigger-plugin"},
        "reason": "end/trigger nodes are only for workflow mode (use answer node for chat output)",
    },
}


def _check_mode_node_compat(spec: dict[str, Any]) -> list[str]:
    """Check that node types are compatible with the spec's mode.
    From frontend use-available-nodes-meta-data.ts:
    - workflow mode: has end + trigger nodes, no answer
    - advanced-chat mode: has answer, no end + trigger nodes"""
    mode = spec.get("mode", "")
    rules = _MODE_NODE_RULES.get(mode)
    if not rules:
        return []
    forbidden = rules["forbidden"]
    if not forbidden:
        return []
    reason = rules["reason"]
    errors: list[str] = []
    for n in spec.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        ntype = n.get("type", "")
        if ntype in forbidden:
            errors.append(
                f"node {n.get('id', '?')!r} ({ntype}): {reason}"
            )
    return errors


def _check_edge_coverage(spec: dict[str, Any], nodes_by_id: dict[str, dict]) -> list[str]:
    """Check that if a node references another node's output via value_selector,
    there is an edge connecting them (directly or transitively).

    Without this, a node can reference a variable from a node it has no edge
    connection to - the Dify frontend checklist reports "dependency variable
    not found" on import."""
    edges = spec.get("edges", []) or []
    # Build adjacency: source -> set of targets
    adjacency: dict[str, set[str]] = {}
    for e in edges:
        if isinstance(e, dict):
            adjacency.setdefault(e.get("source", ""), set()).add(e.get("target", ""))

    # Collect each node's variable references that require an edge.
    # Only value_selector (code/end/template-transform inputs) requires an edge;
    # variable_selector (if-else conditions), iterator_selector, output_selector
    # read from the variable pool and don't need a direct edge.
    _EDGE_REQUIRED_PATTERNS = {
        "code": ["variables.*.value_selector"],
        "end": ["outputs.*.value_selector"],
        "template-transform": ["variables.*.value_selector"],
    }
    node_deps: dict[str, set[str]] = {}  # node_id -> set of referenced node ids
    for node in nodes_by_id.values():
        nid = node.get("id", "")
        ntype = node.get("type", "")
        deps: set[str] = set()
        for pattern in _EDGE_REQUIRED_PATTERNS.get(ntype, []):
            for _path, selector in _walk_pattern(node, pattern):
                if isinstance(selector, list) and len(selector) >= 2:
                    target_id = selector[0]
                    if target_id and target_id not in ("env", "sys", "conversation") and target_id != nid:
                        deps.add(target_id)
        # template_inputs also need edge coverage
        for item in node.get("template_inputs", []) or []:
            if isinstance(item, list) and len(item) >= 2:
                target_id = item[0]
                if target_id and target_id not in ("env", "sys", "conversation") and target_id != nid:
                    deps.add(target_id)
        if deps:
            node_deps[nid] = deps

    # Build: node_id -> container_id (parent)
    edge_node_to_container: dict[str, str] = {}
    for n in spec.get("nodes", []) or []:
        if isinstance(n, dict) and n.get("type") in ("iteration", "loop"):
            for child_id in n.get("children", []) or []:
                edge_node_to_container[child_id] = n["id"]

    errors: list[str] = []
    for nid, deps in node_deps.items():
        parent = edge_node_to_container.get(nid)
        for dep_id in deps:
            # Skip if dep is the node's own container (container variables
            # like loop.counter / iter.item are from the variable pool, not edges)
            if parent == dep_id:
                continue
            # Determine the path target:
            # - If dep is a sibling (same container): check path dep -> nid directly
            # - If dep is external (outside container): check path dep -> parent
            #   (children can reference any variable visible to their parent)
            if parent and edge_node_to_container.get(dep_id) == parent:
                path_target = nid  # sibling - direct path
            elif parent:
                path_target = parent  # external - path to parent container
            else:
                path_target = nid  # top-level node - direct path
            if path_target == dep_id:
                continue
            if not _has_path(adjacency, dep_id, path_target):
                if path_target != nid:
                    errors.append(
                        f"node {nid!r}: references variable from {dep_id!r} but no edge connects "
                        f"{dep_id!r} -> {path_target!r} (the parent container, directly or transitively). "
                        f"Add an edge to the parent."
                    )
                else:
                    errors.append(
                        f"node {nid!r}: references variable from {dep_id!r} but no edge connects "
                        f"{dep_id!r} -> {nid!r} (directly or transitively). Add an edge."
                    )
    return errors


def _has_path(adjacency: dict[str, set[str]], src: str, dst: str, visited: set[str] | None = None) -> bool:
    """BFS/DFS check: is there a path src -> ... -> dst in the edge graph?"""
    if visited is None:
        visited = set()
    if src == dst:
        return True
    if src in visited:
        return False
    visited.add(src)
    for neighbor in adjacency.get(src, set()):
        if _has_path(adjacency, neighbor, dst, visited):
            return True
    return False


def _check_edges(spec: dict[str, Any], nodes_by_id: dict[str, dict]) -> list[str]:
    """Check edge wiring rules for iteration/loop containers:
    1. A container node must NOT directly connect to its own child (the
       auto-created start node handles subgraph entry).
    2. A child inside a container must NOT connect directly to an external
       node (the container node's output is what external nodes reference)."""
    # Build: container_id -> set of child ids
    container_children: dict[str, set[str]] = {}
    # Build: node_id -> container_id (parent)
    node_to_container: dict[str, str] = {}
    for n in spec.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        if n.get("type") in ("iteration", "loop"):
            cid = n["id"]
            container_children[cid] = set(n.get("children", []) or [])
            for child_id in n.get("children", []) or []:
                node_to_container[child_id] = cid

    # Build: if-else node_id -> set of valid case_ids
    ifelse_handles: dict[str, set[str]] = {}
    for n in spec.get("nodes", []) or []:
        if isinstance(n, dict) and n.get("type") == "if-else":
            cid = n["id"]
            valid = {c.get("case_id") for c in (n.get("cases") or []) if isinstance(c, dict)}
            valid.add("false")  # implicit else branch
            valid.add("source")  # default handle (non-branch edge)
            ifelse_handles[cid] = valid

    errors: list[str] = []
    for e in spec.get("edges", []) or []:
        if not isinstance(e, dict):
            continue
        src = e.get("source", "")
        dst = e.get("target", "")
        src_handle = e.get("src_handle", "source")

        # Rule 1: container -> its own child is wrong (start node handles entry)
        if src in container_children and dst in container_children.get(src, set()):
            errors.append(
                f"edge {src!r} -> {dst!r}: container must not directly connect to its own child. "
                f"The start node auto-connects to entry children; remove this edge."
            )

        # Rule 2: child -> external node is wrong (use container as source)
        src_container = node_to_container.get(src)
        dst_container = node_to_container.get(dst)
        if src_container and src_container != dst_container:
            errors.append(
                f"edge {src!r} -> {dst!r}: node {src!r} is inside container {src_container!r}, "
                f"cannot connect to external node {dst!r}. Use {src_container!r} -> {dst!r} instead."
            )

        # Rule 3: if-else src_handle must match a case_id or "false"
        if src in ifelse_handles:
            valid_handles = ifelse_handles[src]
            if src_handle not in valid_handles:
                errors.append(
                    f"edge {src!r} -> {dst!r}: src_handle {src_handle!r} does not match any case_id "
                    f"in if-else node {src!r}. Valid: {sorted(h for h in valid_handles if h != 'source')}"
                )

    return errors


# Fields where a container node legitimately references its own child(ren).
# Only these allow the container->child reference path.
_CONTAINER_CHILD_FIELDS = {"output_selector"}


def _extract_references(node: dict[str, Any]) -> Iterator[tuple[str, list]]:
    """Yield (field_path, selector) pairs from a spec node's hoisted top-level
    fields + template_inputs. Does NOT read `fields` (@file) - selectors live
    at the spec layer."""
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

    # template_inputs: declared template variable references (design stage)
    for item in node.get("template_inputs", []) or []:
        if isinstance(item, list) and len(item) >= 2:
            yield ("template_inputs", item)


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


# Valid system variable keys (from core/workflow/enums.py SystemVariableKey).
_SYS_VARS = {
    "query", "files", "conversation_id", "user_id", "dialogue_count",
    "app_id", "workflow_id", "workflow_run_id", "timestamp",
    "document_id", "original_document_id", "batch",
    "dataset_id", "datasource_type", "datasource_info", "invoke_from",
}


def _check_reference(
    node: dict[str, Any], path: str, selector: list, nodes_by_id: dict,
    spec: dict[str, Any] | None = None,
) -> list[str]:
    target_id = selector[0]
    var = selector[1] if len(selector) > 1 else ""
    nid = node.get("id", "?")
    full = f"{nid}.{path}" if path else nid

    # Built-in variable scopes - check the variable name exists.
    if target_id == "env":
        if spec is not None:
            env_names = {ev.get("name") for ev in spec.get("environment_variables", []) or [] if isinstance(ev, dict)}
            if var and var not in env_names:
                return [f"{full}: env variable {var!r} not declared in spec.environment_variables"]
        return []
    if target_id == "sys":
        if var and var not in _SYS_VARS:
            return [f"{full}: invalid sys variable {var!r}. Valid: {sorted(_SYS_VARS)}"]
        return []
    if target_id == "conversation":
        if spec is not None:
            conv_names = {cv.get("name") for cv in spec.get("conversation_variables", []) or [] if isinstance(cv, dict)}
            if var and var not in conv_names:
                return [f"{full}: conversation variable {var!r} not declared in spec.conversation_variables"]
        return []

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


def _check_schema_for_complete_nodes(spec: dict[str, Any], nodes_by_id: dict[str, dict]) -> list[str]:
    """For nodes that don't need impl files (start/end/if-else/iteration/loop/
    document-extractor), run full backend schema validation at design stage.
    Reuses build_and_validate_node_data (shared with node check)."""
    from .spec_format import NODES_WITHOUT_INTERNAL_CONFIG
    from .node_builder import build_and_validate_node_data
    errors: list[str] = []
    ver = spec.get("dsl_version", "0.5.0")
    for n in spec.get("nodes", []) or []:
        if not isinstance(n, dict):
            continue
        ntype = n.get("type", "")
        if ntype not in NODES_WITHOUT_INTERNAL_CONFIG:
            continue
        nid = n.get("id", "?")
        # internal=None: no impl file, uses frontend defaults only
        errs = build_and_validate_node_data(ntype, n, None, ver)
        for e in errs:
            errors.append(f"node {nid!r} ({ntype}): {e}")
    return errors
