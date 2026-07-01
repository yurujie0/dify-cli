from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..core import dsl as dsl_mod
from ..core import graph as graph_mod
from ..core.errors import DifyCliError

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _load(file: Path):
    doc = dsl_mod.load(file)
    if "workflow" not in doc.data:
        raise DifyCliError(f"{file} has no 'workflow' section; edges only apply to workflow/advanced-chat apps")
    return doc


@app.command("add")
def add(
    source: str = typer.Argument(..., help="Source node id"),
    target: str = typer.Argument(..., help="Target node id"),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
    source_handle: Optional[str] = typer.Option(None, "--src-handle"),
    target_handle: Optional[str] = typer.Option(None, "--dst-handle"),
    edge_id: Optional[str] = typer.Option(None, "--id"),
) -> None:
    """Add an edge between two nodes."""
    doc = _load(file)
    src_node = graph_mod.find_node(doc.nodes, source)
    if src_node is None:
        raise DifyCliError(f"Source node {source!r} not found")
    dst_node = graph_mod.find_node(doc.nodes, target)
    if dst_node is None:
        raise DifyCliError(f"Target node {target!r} not found")
    src_type = (src_node.get("data") or {}).get("type", "")
    dst_type = (dst_node.get("data") or {}).get("type", "")
    edge = {
        "id": edge_id or graph_mod.new_edge_id(),
        "source": source,
        "target": target,
        "sourceHandle": source_handle or "source",
        "targetHandle": target_handle or "target",
        "type": "custom",
        "zIndex": 0,
        "data": {
            "sourceType": src_type,
            "targetType": dst_type,
            "isInIteration": False,
            "isInLoop": False,
        },
    }
    graph_mod.add_edge(doc, edge)
    dsl_mod.save(file, doc)
    typer.secho(f"Added edge {edge['id']!r}: {source} -> {target}", fg=typer.colors.GREEN)


@app.command("list")
def list_(
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    """List edges."""
    doc = _load(file)
    if not doc.edges:
        typer.echo("(no edges)")
        return
    typer.echo(f"{'ID':<24} {'SOURCE':<24} {'TARGET'}")
    for e in doc.edges:
        typer.echo(f"{e.get('id', ''):<24} {e.get('source', ''):<24} {e.get('target', '')}")


@app.command("remove")
def remove(
    edge_id: str = typer.Argument(...),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    """Remove an edge by id."""
    doc = _load(file)
    if not graph_mod.remove_edge(doc, edge_id):
        raise DifyCliError(f"Edge {edge_id!r} not found")
    dsl_mod.save(file, doc)
    typer.secho(f"Removed edge {edge_id!r}", fg=typer.colors.GREEN)
