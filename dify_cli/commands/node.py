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


@app.command("check")
def check(
    node_id: str = typer.Argument(..., help="The node id as declared in the spec"),
    spec: Path = typer.Option(..., "--spec", "-s", help="Design-stage spec.json (provides IO context + dependency declarations)"),
    fields: Optional[Path] = typer.Option(None, "--fields", help="Override impl file path (default: <spec_dir>/<spec_basename>_impl/<node_id>.json)"),
    dsl_version: Optional[str] = typer.Option(None, "--dsl-version", "-v", help="DSL version (default: from spec or latest)"),
) -> None:
    """Check a single node's internal config against the design spec.

    Used in the implementation stage: a sub-agent fills a node's impl file
    (internal config like code/prompt_template), then runs this to verify
    the merged node data (hoisted IO from spec + internal config) passes
    backend schema validation, and that template variable references
    ({{#node.var#}}) in the internal config point to valid in-scope nodes.

    The impl file path is derived from the spec path by convention:
    spec.json -> impl/<node_id>.json; mitr_spec.json -> mitr_impl/<node_id>.json.
    Override with --fields if needed.
    """
    import json as _json
    from ..core.node_builder import _post_process, fields_dict_to_list, parse_field_value
    from ..core.spec_format import HOISTED_FIELDS, NODES_WITHOUT_INTERNAL_CONFIG, impl_file_for, needs_implementation
    from ..core.spec_validator import _walk_all_strings, _extract_template_refs, _exposed_vars, _in_scope

    spec_data = _json.loads(spec.read_text(encoding="utf-8"))
    # Flatten spec nodes (including children) to find the target.
    flat = []
    for n in spec_data.get("nodes", []):
        flat.append(n)
        if n.get("type") in ("iteration", "loop"):
            for child in n.get("children", []):
                child = dict(child)
                child["_parentId"] = n["id"]
                flat.append(child)
    target_spec = next((n for n in flat if n.get("id") == node_id), None)
    if target_spec is None:
        raise DifyCliError(f"Node {node_id!r} not found in spec {spec}")
    ntype = target_spec.get("type", "")

    # Internal config: from --fields override, or convention-based impl path.
    if not needs_implementation(ntype):
        internal = {}
    else:
        impl_path = fields if fields is not None else impl_file_for(spec, node_id)
        if not impl_path.exists():
            raise DifyCliError(
                f"node {node_id!r} ({ntype}): implementation file not found: {impl_path}\n"
                f"(create it with the node's internal config - code/model/prompt_template/etc)"
            )
        internal = _json.loads(impl_path.read_text(encoding="utf-8"))
        if not isinstance(internal, dict):
            raise DifyCliError(f"impl file must contain a JSON object, got {type(internal).__name__}")

    # Merge hoisted (from spec) + internal. Hoisted wins over impl
    # (spec is the source of truth). If impl accidentally includes a
    # hoisted field, just drop it - no error.
    hoisted = {f: target_spec[f] for f in HOISTED_FIELDS.get(ntype, []) if f in target_spec}
    for f in list(internal):
        if f in hoisted:
            del internal[f]
    merged = {**internal, **hoisted}

    nodes_by_id = {n["id"]: n for n in flat}
    ver = dsl_version or spec_data.get("dsl_version") or "0.5.0"

    errors: list[str] = []
    # 1. Schema validation on merged data.
    try:
        schema = get_node_schema(ver, ntype)
        data = dict(merged)
        data.setdefault("type", ntype)
        data.setdefault("title", target_spec.get("title", ""))
        _post_process(ntype, data)
        validate_node_data(ntype, data, schema)
    except DifyCliError as e:
        errors.append(f"schema: {e}")

    # 2. Template variable references ({{#node.var#}}) in internal config.
    # {{#env.VAR#}} and {{#sys.VAR#}} reference environment/system variables,
    # not nodes - skip them.
    _BUILTIN_SCOPES = {"env", "sys"}
    for path, value in _walk_all_strings(internal):
        for ref_id, ref_var in _extract_template_refs(value):
            if ref_id in _BUILTIN_SCOPES:
                continue
            ref_node = nodes_by_id.get(ref_id)
            if ref_node is None:
                errors.append(f"{path}: template ref {ref_id!r} does not exist in spec")
                continue
            if not _in_scope(ref_node, target_spec, path):
                errors.append(f"{path}: template ref {ref_id!r} is out of scope (inside container)")
                continue
            if ref_node.get("type") not in {"tool", "agent"}:
                exposed = _exposed_vars(ref_node, target_spec)
                if ref_var not in exposed:
                    errors.append(f"{path}: {ref_id!r} does not expose {ref_var!r}. Exposes: {sorted(exposed) or '(none)'}")

    if errors:
        for e in errors:
            typer.secho(f"FAIL {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(f"OK node {node_id!r} ({ntype}) internal config is valid", fg=typer.colors.GREEN)


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
