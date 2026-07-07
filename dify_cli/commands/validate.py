from __future__ import annotations

from pathlib import Path

import typer

from ..core import dsl as dsl_mod
from ..core import graph as graph_mod
from ..core.errors import DifyCliError
from ..core.node_builder import validate_node_data
from ..core.schema_store import get_node_schema, load_bundle


def validate(
    file: Path = typer.Argument(Path("dsl.yaml"), help="DSL YAML file"),
) -> None:
    """Validate a DSL file: top-level shape, every node's schema, and graph topology."""
    doc = dsl_mod.load(file)
    dsl_version = doc.version
    try:
        bundle = load_bundle(dsl_version)
    except DifyCliError as e:
        raise typer.Exit(str(e)) from e

    errors: list[str] = []

    if "workflow" in doc.data:
        node_types = bundle["node_types"]
        for n in doc.nodes:
            nid = n.get("id", "<no-id>")
            data = n.get("data") or {}
            ntype = data.get("type")
            if not ntype:
                errors.append(f"node {nid}: missing data.type")
                continue
            if ntype not in node_types:
                errors.append(f"node {nid}: unknown node type {ntype!r} for DSL {dsl_version}")
                continue
            try:
                validate_node_data(ntype, data, node_types[ntype])
            except DifyCliError as e:
                errors.append(f"node {nid}: {e}")

        errors.extend(graph_mod.validate_graph(doc))

    if errors:
        for e in errors:
            typer.secho(f"FAIL {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(f"OK {file} is valid (dsl_version={dsl_version})", fg=typer.colors.GREEN)
