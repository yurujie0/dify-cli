from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..core import dsl as dsl_mod
from ..core import graph as graph_mod
from ..core.errors import DifyCliError
from ..core.node_builder import build_node, validate_node_data
from ..core.schema_store import get_node_schema, node_types

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _load(file: Path):
    doc = dsl_mod.load(file)
    if "workflow" not in doc.data:
        raise DifyCliError(f"{file} has no 'workflow' section (mode={doc.app_mode}); only workflow/advanced-chat apps support nodes")
    return doc


@app.command("add")
def add(
    node_type: str = typer.Argument(..., help="Node type, e.g. llm / start / end / http-request"),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    field: list[str] = typer.Option([], "--field", help="key=value, dotted keys supported; JSON if value starts with { or ["),
) -> None:
    """Add a node to the workflow graph.

    Node id is auto-generated as a millisecond timestamp (matching the
    Dify frontend's Date.now() algorithm). Iteration/loop nodes also
    auto-create their start child node with id '<parent_id>start'.
    """
    doc = _load(file)
    node = build_node(
        node_type=node_type,
        dsl_version=doc.version,
        title=title,
        fields=field or None,
    )
    graph_mod.add_node(doc, node)

    # Iteration/loop nodes auto-create their start child node (frontend behavior).
    # Mirrors web/app/components/workflow/utils/node.ts:getIterationStartNode.
    if node_type in ("iteration", "loop"):
        start_type = "iteration-start" if node_type == "iteration" else "loop-start"
        start_node = build_node(
            node_type=start_type,
            dsl_version=doc.version,
            title="",
            fields=None,
            position={"x": 24, "y": 68},
        )
        start_node["id"] = graph_mod.new_iteration_start_id(node["id"])
        start_node["parentId"] = node["id"]
        start_node["zIndex"] = 1002  # ITERATION/LOOP_CHILDREN_Z_INDEX
        start_node["selectable"] = False
        start_node["draggable"] = False
        start_node["data"]["isInIteration"] = node_type == "iteration"
        start_node["data"]["isInLoop"] = node_type == "loop"
        # Link parent's start_node_id
        node["data"]["start_node_id"] = start_node["id"]
        # Parent iteration/loop node gets zIndex 1 (ITERATION/LOOP_NODE_Z_INDEX)
        node["zIndex"] = 1
        graph_mod.add_node(doc, start_node)

    dsl_mod.save(file, doc)
    typer.secho(f"Added node {node['id']!r} (type={node_type})", fg=typer.colors.GREEN)


@app.command("list")
def list_(
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    """List nodes in the workflow graph."""
    doc = _load(file)
    if not doc.nodes:
        typer.echo("(no nodes)")
        return
    typer.echo(f"{'ID':<24} {'TYPE':<22} {'TITLE'}")
    for n in doc.nodes:
        data = n.get("data") or {}
        typer.echo(f"{n.get('id', ''):<24} {data.get('type', ''):<22} {data.get('title', '')}")


@app.command("show")
def show(
    node_id: str = typer.Argument(...),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    """Show a single node's data."""
    doc = _load(file)
    node = graph_mod.find_node(doc.nodes, node_id)
    if node is None:
        raise DifyCliError(f"Node {node_id!r} not found")
    import json as _json
    typer.echo(_json.dumps(node, indent=2, ensure_ascii=False))


@app.command("edit")
def edit(
    node_id: str = typer.Argument(...),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
    field: list[str] = typer.Option([], "--field", help="key=value to set (dotted keys supported)"),
) -> None:
    """Edit fields on an existing node."""
    from ..core.node_builder import _post_process, apply_fields
    doc = _load(file)
    node = graph_mod.find_node(doc.nodes, node_id)
    if node is None:
        raise DifyCliError(f"Node {node_id!r} not found")
    data = node.setdefault("data", {})
    apply_fields(data, field)
    ntype = data.get("type")
    if ntype:
        _post_process(ntype, data)
        schema = get_node_schema(doc.version, ntype)
        validate_node_data(ntype, data, schema)
    dsl_mod.save(file, doc)
    typer.secho(f"Updated node {node_id!r}", fg=typer.colors.GREEN)


@app.command("remove")
def remove(
    node_id: str = typer.Argument(...),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    """Remove a node (and its connected edges)."""
    doc = _load(file)
    if not graph_mod.remove_node(doc, node_id):
        raise DifyCliError(f"Node {node_id!r} not found")
    dsl_mod.save(file, doc)
    typer.secho(f"Removed node {node_id!r}", fg=typer.colors.GREEN)


@app.command("types")
def types(
    dsl_version: Optional[str] = typer.Option(
        None, "--dsl-version", "-v",
        help="DSL version to list types for (defaults to the latest bundled version)",
    ),
    file: Optional[Path] = typer.Option(
        None, "--file", "-f",
        help="DSL file to read the version from (overrides --dsl-version)",
    ),
) -> None:
    """List node types known by the DSL's schema bundle.

    Without -f or -v, lists types for the latest bundled DSL version —
    useful for agents probing what's available before scaffolding a DSL.
    """
    if file is not None:
        doc = dsl_mod.load(file)
        ver = doc.version
    elif dsl_version is not None:
        ver = dsl_version
    else:
        from ..core.schema_store import available_versions
        versions = available_versions()
        if not versions:
            raise DifyCliError("No schema bundles installed")
        ver = versions[-1]
    for t in node_types(ver):
        typer.echo(t)
