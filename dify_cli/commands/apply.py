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
    _make_condition_ids_deterministic(doc)

    dsl_mod.save(file, doc)
    typer.secho(
        f"Applied spec {spec} -> {file} "
        f"({len(doc.nodes)} nodes, {len(doc.edges)} edges, dsl_version={dsl_version})",
        fg=typer.colors.GREEN,
    )


def _build_nodes(doc, nodes: list, dsl_version: str) -> None:
    top_index = 0
    for n in nodes:
        if not isinstance(n, dict) or "id" not in n or "type" not in n:
            raise DifyCliError(f"Each node must have 'id' and 'type'; got {n!r}")
        node = build_node(
            node_type=n["type"],
            dsl_version=dsl_version,
            title=n.get("title"),
            fields=fields_dict_to_list(n.get("fields") or {}),
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
                    fields=fields_dict_to_list(child.get("fields") or {}),
                )
                cnode["id"] = child["id"]
                attach_to_parent(cnode, node["id"], n["type"])
                graph_mod.add_node(doc, cnode)


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
