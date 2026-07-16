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


# Deprecated: declare nodes in the spec and use `dify-cli apply`.
# @app.command("add")
def add(
    node_type: str = typer.Argument(..., help="Node type, e.g. llm / start / end / http-request"),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    parent: Optional[str] = typer.Option(None, "--parent", "-p", help="Parent iteration/loop node id (places this node inside the container)"),
    field: list[str] = typer.Option([], "--field", help="key=value, dotted keys supported; JSON if value starts with { or ["),
    fields_file: Optional[Path] = typer.Option(None, "--fields-file", help="Read field overrides from a JSON file (object of {key: value}); avoids shell quoting issues"),
) -> None:
    """Add a node to the workflow graph.

    Node id is auto-generated as a millisecond timestamp (matching the
    Dify frontend's Date.now() algorithm). Iteration/loop nodes also
    auto-create their start child node with id '<parent_id>start'.

    Use --parent to place a node inside an iteration/loop container;
    this sets parentId, isInIteration/isInLoop, and the child zIndex so
    ReactFlow renders it inside the container.

    Use --fields-file to load field overrides from a JSON file when
    values contain shell metacharacters (& | ; > < space quote) that
    make --field quoting error-prone.
    """
    fields = list(field)
    if fields_file is not None:
        import json as _json
        data = _json.loads(fields_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise DifyCliError(f"--fields-file must contain a JSON object, got {type(data).__name__}")
        from ..core.node_builder import fields_dict_to_list
        fields.extend(fields_dict_to_list(data))

    doc = _load(file)
    node = build_node(
        node_type=node_type,
        dsl_version=doc.version,
        title=title,
        fields=fields or None,
    )

    # Attach to a parent iteration/loop container if requested.
    if parent:
        parent_node = graph_mod.find_node(doc.nodes, parent)
        if parent_node is None:
            raise DifyCliError(f"Parent node {parent!r} not found")
        parent_type = (parent_node.get("data") or {}).get("type")
        if parent_type not in ("iteration", "loop"):
            raise DifyCliError(f"Parent {parent!r} is {parent_type!r}, not iteration/loop")
        from ..core.node_builder import attach_to_parent
        attach_to_parent(node, parent, parent_type)

    graph_mod.add_node(doc, node)

    start_node = None
    # Iteration/loop nodes auto-create their start child node (frontend behavior).
    if node_type in ("iteration", "loop"):
        from ..core.node_builder import create_container_start
        start_node = create_container_start(node, node_type, doc.version)
        graph_mod.add_node(doc, start_node)

    dsl_mod.save(file, doc)
    if node_type in ("iteration", "loop") and start_node is not None:
        typer.secho(
            f"Added node {node['id']!r} (type={node_type}), "
            f"start child {start_node['id']!r} (type={start_node['data']['type']})",
            fg=typer.colors.GREEN,
        )
    else:
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


# Deprecated: declare nodes in the spec and use `dify-cli apply`.
# @app.command("remove")
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
