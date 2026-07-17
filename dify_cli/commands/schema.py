from __future__ import annotations

import json
from typing import Optional

import typer

from ..core.errors import DifyCliError
from ..core.schema_store import available_versions, get_node_schema, load_bundle, node_types

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Inspect bundled node schemas.")


@app.command("node")
def node(
    node_type: str = typer.Argument(..., help="Node type, e.g. start / llm / if-else / iteration"),
    dsl_version: Optional[str] = typer.Option(None, "--dsl-version", "-v", help="DSL version (default: latest)"),
    required_only: bool = typer.Option(False, "--required-only", help="Print only required field names"),
) -> None:
    """Show the JSON Schema for a node type's `data` object.

    Use this to discover which fields a node requires and what enum
    values are accepted - without reading source files.
    """
    ver = dsl_version or _latest_version()
    schema = get_node_schema(ver, node_type)
    from ..core.spec_format import HOISTED_FIELDS
    hoisted = set(HOISTED_FIELDS.get(node_type, []))
    if required_only:
        # Exclude hoisted fields - they live at the spec layer, not in @file.
        required = [f for f in schema.get("required", []) if f not in hoisted]
        typer.echo(json.dumps(required, indent=2))
    else:
        # Strip hoisted fields from properties so the agent only sees
        # internal config fields (what goes in @file).
        import copy
        filtered = copy.deepcopy(schema)
        props = filtered.get("properties", {})
        for f in hoisted:
            props.pop(f, None)
        if "required" in filtered:
            filtered["required"] = [f for f in filtered["required"] if f not in hoisted]
        typer.echo(json.dumps(filtered, indent=2, ensure_ascii=False))


@app.command("types")
def types(
    dsl_version: Optional[str] = typer.Option(None, "--dsl-version", "-v", help="DSL version (default: latest)"),
) -> None:
    """List all node types in the bundled schema."""
    ver = dsl_version or _latest_version()
    for t in node_types(ver):
        typer.echo(t)


@app.command("enum")
def enum(
    node_type: str = typer.Argument(..., help="Node type, e.g. start / code"),
    field_name: str = typer.Argument(..., help="Enum field name, e.g. type / code_language"),
    dsl_version: Optional[str] = typer.Option(None, "--dsl-version", "-v", help="DSL version (default: latest)"),
) -> None:
    """Print the allowed values for a node's enum field.

    Looks up the field in the node's top-level properties and nested $defs.
    Useful when unsure what values a field accepts (e.g. start.variables[].type).
    """
    ver = dsl_version or _latest_version()
    schema = get_node_schema(ver, node_type)
    props = schema.get("properties", {})
    defs = schema.get("$defs", {})

    # Top-level property enum
    if field_name in props:
        sub = props[field_name]
        if "enum" in sub:
            typer.echo(json.dumps(sub["enum"], indent=2))
            return
        # $ref into $defs
        ref = sub.get("$ref") or (sub.get("items", {}).get("$ref") if isinstance(sub.get("items"), dict) else None)
        if ref:
            def_name = ref.split("/")[-1]
            target = defs.get(def_name, {})
            if "enum" in target:
                typer.echo(json.dumps(target["enum"], indent=2))
                return
            if "properties" in target and field_name in target.get("properties", {}):
                _print_enum_or_error(def_name, target["properties"][field_name], defs, field_name)
                return

    # Search nested $defs for a property with that name
    for def_name, def_schema in defs.items():
        if field_name in def_schema.get("properties", {}):
            sub = def_schema["properties"][field_name]
            if "enum" in sub:
                typer.echo(json.dumps(sub["enum"], indent=2))
                return
            ref = sub.get("$ref")
            if ref:
                target = defs.get(ref.split("/")[-1], {})
                if "enum" in target:
                    typer.echo(json.dumps(target["enum"], indent=2))
                    return

    raise DifyCliError(
        f"No enum field {field_name!r} found on node type {node_type!r}. "
        f"Run `dify-cli schema node {node_type}` to inspect the full schema."
    )


def _print_enum_or_error(def_name: str, sub: dict, defs: dict, field_name: str) -> None:
    if "enum" in sub:
        typer.echo(json.dumps(sub["enum"], indent=2))
        return
    ref = sub.get("$ref")
    if ref:
        target = defs.get(ref.split("/")[-1], {})
        if "enum" in target:
            typer.echo(json.dumps(target["enum"], indent=2))
            return
    raise DifyCliError(f"Field {field_name!r} on {def_name!r} is not an enum.")


def _latest_version() -> str:
    versions = available_versions()
    if not versions:
        raise DifyCliError("No schema bundles installed")
    return versions[-1]
