from __future__ import annotations

import json
from pathlib import Path

import typer

from ..core import dsl as dsl_mod
from ..core import graph as graph_mod
from ..core.errors import DifyCliError
from ..core.node_builder import (
    attach_to_parent,
    build_node,
    create_container_start,
    fields_dict_to_list,
)
from ..core.schema_store import available_versions


def apply(
    spec: Path = typer.Option(..., "--spec", "-s", help="Path to the workflow spec JSON file"),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f", help="Output DSL YAML path"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing file"),
) -> None:
    """Generate a complete DSL from a declarative spec file.

    The spec is the single source of truth: it lists nodes (with stable
    string ids), edges, and per-node field overrides (values support
    @file). Re-running apply with an edited spec regenerates the DSL
    deterministically - no drift, no N node-add commands.

    Spec format:
      {
        "mode": "workflow", "name": "...", "dsl_version": "0.5.0",
        "nodes": [{"id": "start", "type": "start", "fields": {...},
                   "children": [...]}],   # children only for iteration/loop
        "edges": [{"source": "start", "target": "llm", "src_handle": "true"}]
      }
    """
    if not spec.exists():
        raise DifyCliError(f"Spec file not found: {spec}")
    try:
        spec_data = json.loads(spec.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DifyCliError(f"Invalid JSON in spec {spec}: {e}") from e

    if not isinstance(spec_data, dict):
        raise DifyCliError(f"Spec must be a JSON object, got {type(spec_data).__name__}")

    mode = spec_data.get("mode")
    name = spec_data.get("name")
    if not mode or not name:
        raise DifyCliError("Spec must contain 'mode' and 'name'")

    versions = available_versions()
    dsl_version = spec_data.get("dsl_version") or (versions[-1] if versions else "0.5.0")
    if dsl_version not in versions:
        raise DifyCliError(
            f"DSL version {dsl_version!r} has no schema bundle. Available: {', '.join(versions) or 'none'}"
        )

    if file.exists() and not force:
        raise DifyCliError(f"{file} already exists; pass --force to overwrite")

    # Defensive: validate variable references before generating. Run
    # `dify-cli spec validate` in the design stage to iterate on errors.
    from ..core.spec_validator import validate_spec
    spec_errors = validate_spec(spec_data)
    if spec_errors:
        typer.secho("Spec has invalid variable references. Run `dify-cli spec validate --spec` for details:", fg=typer.colors.RED)
        for e in spec_errors:
            typer.secho(f"FAIL {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    doc = dsl_mod.init_skeleton(
        mode=mode,
        name=name,
        dsl_version=dsl_version,
        description=spec_data.get("description", ""),
    )

    if "workflow" not in doc.data:
        raise DifyCliError(
            f"apply only supports workflow/advanced-chat modes (got {mode!r}); "
            "chat/completion apps have no graph to build"
        )

    _build_nodes(doc, spec_data.get("nodes", []), dsl_version, spec)
    _build_edges(doc, spec_data.get("edges", []))
    _connect_container_starts(doc)
    _build_variables(doc, spec_data)
    _make_condition_ids_deterministic(doc)

    dsl_mod.save(file, doc)
    typer.secho(
        f"Applied spec {spec} -> {file} "
        f"({len(doc.nodes)} nodes, {len(doc.edges)} edges, dsl_version={dsl_version})",
        fg=typer.colors.GREEN,
    )


def _resolve_node_fields(n: dict, node_type: str, spec_path) -> dict:
    """Merge a node's internal config (from convention-based impl file) with
    its hoisted IO/dependency fields (which live at the spec node top-level).

    Impl file path: <spec_dir>/<spec_basename>_impl/<node_id>.json
    (e.g. spec.json -> impl/code1.json; mitr_spec.json -> mitr_impl/code1.json)

    Nodes in NODES_WITHOUT_INTERNAL_CONFIG have no impl file - their required
    fields are all hoisted or have frontend defaults.
    """
    from ..core.spec_format import HOISTED_FIELDS, NODES_WITHOUT_INTERNAL_CONFIG, impl_file_for

    nid = n.get("id", "?")
    hoisted = {f: n[f] for f in HOISTED_FIELDS.get(node_type, []) if f in n}

    if node_type in NODES_WITHOUT_INTERNAL_CONFIG:
        internal = {}
    else:
        impl_path = impl_file_for(spec_path, nid)
        if not impl_path.exists():
            raise DifyCliError(
                f"node {nid!r} ({node_type}): implementation file not found: {impl_path}\n"
                f"(create it with the node's internal config - code/model/prompt_template/etc)"
            )
        import json as _json
        try:
            internal = _json.loads(impl_path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError as e:
            raise DifyCliError(f"node {nid!r} impl file {impl_path} is not valid JSON: {e}") from e
        if not isinstance(internal, dict):
            raise DifyCliError(f"node {nid!r} impl file must contain a JSON object, got {type(internal).__name__}")
        # Drop any hoisted field the impl file accidentally includes - spec wins.
        for f in list(internal):
            if f in hoisted:
                del internal[f]

    return _resolve_atfile_strings({**internal, **hoisted})


def _resolve_atfile_strings(obj):
    """Walk a dict/list and replace any string value starting with '@' with
    the file's contents (raw text). Lets a fields JSON reference external
    files for individual long values (e.g. code) while keeping the rest inline.
    Does NOT recurse into the file contents."""
    from ..core.node_builder import parse_field_value
    if isinstance(obj, dict):
        return {k: _resolve_atfile_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_atfile_strings(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("@") and not obj.startswith("@-"):
        from pathlib import Path as _Path
        target = obj[1:]
        p = _Path(target)
        if p.exists():
            return p.read_text(encoding="utf-8")
    return obj


def _build_nodes(doc, nodes: list, dsl_version: str, spec_path) -> None:
    # Index all nodes by id (children are now top-level, referenced by id).
    nodes_by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

    # Collect all child ids so we can skip them at the top level.
    child_ids: set[str] = set()
    for n in nodes:
        if isinstance(n, dict) and n.get("type") in ("iteration", "loop"):
            for cid in n.get("children", []):
                child_ids.add(cid)

    top_index = 0
    for n in nodes:
        if not isinstance(n, dict) or "id" not in n or "type" not in n:
            raise DifyCliError(f"Each node must have 'id' and 'type'; got {n!r}")

        # Skip child nodes here - they're built when their parent is processed.
        if n["id"] in child_ids:
            continue

        node = build_node(
            node_type=n["type"],
            dsl_version=dsl_version,
            title=n.get("title"),
            fields_dict=_resolve_node_fields(n, n["type"], spec_path),
        )
        node["id"] = n["id"]
        # Linear layout for top-level nodes (Dify frontend can auto-arrange).
        node["position"] = {"x": top_index * 300, "y": 0}
        node["positionAbsolute"] = {"x": top_index * 300, "y": 0}
        top_index += 1
        graph_mod.add_node(doc, node)

        if n["type"] in ("iteration", "loop"):
            start_node = create_container_start(node, n["type"], dsl_version)
            graph_mod.add_node(doc, start_node)
            for child_id in n.get("children", []):
                child = nodes_by_id.get(child_id)
                if child is None:
                    raise DifyCliError(
                        f"node {n['id']!r} ({n['type']}): child {child_id!r} not found in spec.nodes"
                    )
                cnode = build_node(
                    node_type=child["type"],
                    dsl_version=dsl_version,
                    title=child.get("title"),
                    fields_dict=_resolve_node_fields(child, child["type"], spec_path),
                )
                cnode["id"] = child["id"]
                attach_to_parent(cnode, node["id"], n["type"])
                graph_mod.add_node(doc, cnode)
            # Subgraph entry edges (start -> in-degree-0 children) are wired
            # after all spec edges are built, in _connect_container_starts.


def _build_edges(doc, edges: list) -> None:
    for e in edges:
        if not isinstance(e, dict) or "source" not in e or "target" not in e:
            raise DifyCliError(f"Each edge must have 'source' and 'target'; got {e!r}")
        src, dst = e["source"], e["target"]
        if graph_mod.find_node(doc.nodes, src) is None:
            raise DifyCliError(f"Edge source {src!r} not found in nodes")
        if graph_mod.find_node(doc.nodes, dst) is None:
            raise DifyCliError(f"Edge target {dst!r} not found in nodes")
        # Deterministic edge id so re-applying the same spec yields identical
        # output (node ids are already stable from the spec).
        handle = e.get("src_handle")
        edge_id = f"{src}-{dst}" if not handle else f"{src}-{handle}-{dst}"
        edge = graph_mod.build_edge(
            doc, src, dst,
            source_handle=handle,
            target_handle=e.get("dst_handle"),
            edge_id=edge_id,
        )
        graph_mod.add_edge(doc, edge)


def _make_condition_ids_deterministic(doc) -> None:
    """Replace uuid condition ids with deterministic `<node_id>-cond-<index>` so
    re-applying the same spec yields byte-identical output. Condition ids are
    internal React keys; their exact value doesn't matter, only uniqueness.
    """
    for node in doc.nodes:
        nid = node.get("id", "")
        data = node.get("data") or {}
        idx = 0
        for case in data.get("cases") or []:
            for cond in case.get("conditions") or []:
                cond["id"] = f"{nid}-cond-{idx}"
                idx += 1
        for bc in data.get("break_conditions") or []:
            bc["id"] = f"{nid}-cond-{idx}"
            idx += 1


def _connect_container_starts(doc) -> None:
    """Wire each iteration/loop start node to its in-degree-0 children.

    A child with no incoming spec edge is a subgraph entry point and must be
    connected to the auto-created start node. Handles parallel entry points
    (multiple in-degree-0 children) and chained children (only the first has
    in-degree 0). Children already targeted by a spec edge are reached via
    that edge and are left alone.
    """
    # Collect all edge targets once.
    targeted = {e.get("target") for e in doc.edges}
    for node in doc.nodes:
        data = node.get("data") or {}
        if data.get("type") not in ("iteration", "loop"):
            continue
        start_id = data.get("start_node_id")
        if not start_id:
            continue
        # Children = nodes whose parentId is this container, excluding the
        # start node itself.
        parent_id = node["id"]
        entry_children = [
            n["id"] for n in doc.nodes
            if n.get("parentId") == parent_id
            and n["id"] != start_id
            and (n.get("data") or {}).get("type") not in ("iteration-start", "loop-start")
            and n["id"] not in targeted
        ]
        for child_id in entry_children:
            edge = graph_mod.build_edge(
                doc, start_id, child_id,
                edge_id=f"{start_id}-{child_id}",
            )
            graph_mod.add_edge(doc, edge)


def _build_variables(doc, spec_data: dict) -> None:
    """Generate environment_variables and conversation_variables from the spec.

    Lets the spec declare variables declaratively (instead of `var env set`
    / `var conversation set`), keeping the spec as the single source of truth.
    Env var values support @file (for URLs blocked by agent frameworks).
    """
    from ..core.node_builder import parse_field_value
    # Common agent mistake: "text" (a start variable type) instead of "string".
    _VAR_TYPE_NORMALIZE = {"text": "string"}
    for ev in spec_data.get("environment_variables", []) or []:
        vt = _VAR_TYPE_NORMALIZE.get(ev.get("value_type", "string"), ev.get("value_type", "string"))
        doc.environment_variables.append({
            "name": ev["name"],
            "value": parse_field_value(ev["value"]) if isinstance(ev["value"], str) else ev["value"],
            "value_type": vt,
        })
    for cv in spec_data.get("conversation_variables", []) or []:
        vt = _VAR_TYPE_NORMALIZE.get(cv.get("value_type", "string"), cv.get("value_type", "string"))
        doc.conversation_variables.append({
            "name": cv["name"],
            "value_type": vt,
            "value": cv.get("value"),
            "description": cv.get("description", ""),
        })
