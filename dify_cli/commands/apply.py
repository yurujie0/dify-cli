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

    _build_nodes(doc, spec_data.get("nodes", []), dsl_version)
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


def _resolve_node_fields(n: dict, node_type: str) -> dict:
    """Merge a node's internal config (@file or inline dict) with its hoisted
    IO/dependency fields (which live at the spec node top-level).

    Hoisted fields (variables, outputs, cases, etc.) contain cross-node
    selectors and are validated at design stage; internal config (code,
    prompt_template, model) lives in @file and is filled at implementation
    stage. apply merges them to form the full node data.
    """
    from ..core.node_builder import parse_field_value
    from ..core.spec_format import HOISTED_FIELDS, IGNORED_SPEC_FIELDS

    # Internal config: fields is @file (string -> JSON object) or inline dict.
    raw_fields = n.get("fields")
    if isinstance(raw_fields, str):
        if not raw_fields.startswith("@"):
            raise DifyCliError(f"node {n.get('id')!r} fields string must be @file reference, got {raw_fields!r}")
        target = raw_fields[1:]
        from pathlib import Path as _Path
        p = _Path(target)
        if not p.exists():
            raise DifyCliError(f"node {n.get('id')!r} fields @file not found: {target}")
        import json as _json
        try:
            internal = _json.loads(p.read_text(encoding="utf-8"))
        except _json.JSONDecodeError as e:
            raise DifyCliError(f"node {n.get('id')!r} fields @file {target} is not valid JSON: {e}") from e
        if not isinstance(internal, dict):
            raise DifyCliError(
                f"node {n.get('id')!r} fields @file must contain a JSON object, got {type(internal).__name__}"
            )
    elif isinstance(raw_fields, dict):
        internal = raw_fields
    elif raw_fields is None:
        internal = {}
    else:
        raise DifyCliError(f"node {n.get('id')!r} fields must be @file string or object, got {type(raw_fields).__name__}")

    # Hoisted fields from spec node top-level.
    hoisted = {f: n[f] for f in HOISTED_FIELDS.get(node_type, []) if f in n}

    # Disallow overlap (ambiguous - is it IO or internal?).
    overlap = set(internal) & set(hoisted)
    if overlap:
        raise DifyCliError(
            f"node {n.get('id')!r}: fields {sorted(overlap)} appear in both @file and spec top-level. "
            f"Hoisted IO fields ({sorted(hoisted)}) must not be in @file."
        )

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


def _build_nodes(doc, nodes: list, dsl_version: str) -> None:
    top_index = 0
    for n in nodes:
        if not isinstance(n, dict) or "id" not in n or "type" not in n:
            raise DifyCliError(f"Each node must have 'id' and 'type'; got {n!r}")
        node = build_node(
            node_type=n["type"],
            dsl_version=dsl_version,
            title=n.get("title"),
            fields_dict=_resolve_node_fields(n, n["type"]),
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
            for child in n.get("children", []):
                if not isinstance(child, dict) or "id" not in child or "type" not in child:
                    raise DifyCliError(f"Each child node must have 'id' and 'type'; got {child!r}")
                cnode = build_node(
                    node_type=child["type"],
                    dsl_version=dsl_version,
                    title=child.get("title"),
                    fields_dict=_resolve_node_fields(child, child["type"]),
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
    for ev in spec_data.get("environment_variables", []) or []:
        doc.environment_variables.append({
            "name": ev["name"],
            "value": parse_field_value(ev["value"]) if isinstance(ev["value"], str) else ev["value"],
            "value_type": ev.get("value_type", "string"),
        })
    for cv in spec_data.get("conversation_variables", []) or []:
        doc.conversation_variables.append({
            "name": cv["name"],
            "value_type": cv.get("value_type", "string"),
            "value": cv.get("value"),
            "description": cv.get("description", ""),
        })
