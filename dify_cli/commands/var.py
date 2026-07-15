from __future__ import annotations

from pathlib import Path

import typer

from ..core import dsl as dsl_mod
from ..core.errors import DifyCliError

app = typer.Typer(no_args_is_help=True, add_completion=False)
env_app = typer.Typer(no_args_is_help=True, add_completion=False)
conv_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(env_app, name="env")
app.add_typer(conv_app, name="conversation")


def _load(file: Path):
    doc = dsl_mod.load(file)
    if "workflow" not in doc.data:
        raise DifyCliError(f"{file} has no 'workflow' section; variables only apply to workflow/advanced-chat apps")
    return doc


def _find(vars_: list[dict], name: str) -> dict | None:
    return next((v for v in vars_ if v.get("name") == name), None)


@env_app.command("set")
def env_set(
    name: str = typer.Argument(...),
    value: str = typer.Argument(..., help="Env var value. Use @file to read from a file (for URLs blocked by agent frameworks)."),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    """Set (or update) an environment variable.

    The value supports `@file` syntax (read from a file) - use this for
    URLs, which agent frameworks block when inlined in the command line.
    """
    from ..core.node_builder import parse_field_value
    resolved = parse_field_value(value)
    doc = _load(file)
    existing = _find(doc.environment_variables, name)
    if existing:
        existing["value"] = resolved
    else:
        doc.environment_variables.append({"name": name, "value": resolved, "value_type": "string"})
    dsl_mod.save(file, doc)
    typer.secho(f"Set env var {name!r}", fg=typer.colors.GREEN)


@env_app.command("get")
def env_get(
    name: str = typer.Argument(...),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    doc = _load(file)
    v = _find(doc.environment_variables, name)
    if v is None:
        raise DifyCliError(f"Env var {name!r} not found")
    typer.echo(v.get("value", ""))


@env_app.command("list")
def env_list(
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    doc = _load(file)
    if not doc.environment_variables:
        typer.echo("(no env vars)")
        return
    typer.echo(f"{'NAME':<24} {'TYPE':<10} {'VALUE'}")
    for v in doc.environment_variables:
        typer.echo(f"{v.get('name', ''):<24} {v.get('value_type', ''):<10} {v.get('value', '')}")


@env_app.command("remove")
def env_remove(
    name: str = typer.Argument(...),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    doc = _load(file)
    before = len(doc.environment_variables)
    doc.environment_variables = [v for v in doc.environment_variables if v.get("name") != name]
    if len(doc.environment_variables) == before:
        raise DifyCliError(f"Env var {name!r} not found")
    dsl_mod.save(file, doc)
    typer.secho(f"Removed env var {name!r}", fg=typer.colors.GREEN)


@conv_app.command("set")
def conv_set(
    name: str = typer.Argument(...),
    value_type: str = typer.Option("string", "--type", help="Value type: string|number|object|array[string]..."),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
    description: str = typer.Option("", "--description"),
) -> None:
    """Set (or update) a conversation variable."""
    doc = _load(file)
    existing = _find(doc.conversation_variables, name)
    if existing:
        existing["value_type"] = value_type
        if description:
            existing["description"] = description
    else:
        item: dict = {"name": name, "value_type": value_type, "value": None, "description": description}
        doc.conversation_variables.append(item)
    dsl_mod.save(file, doc)
    typer.secho(f"Set conversation var {name!r}", fg=typer.colors.GREEN)


@conv_app.command("list")
def conv_list(
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    doc = _load(file)
    if not doc.conversation_variables:
        typer.echo("(no conversation vars)")
        return
    typer.echo(f"{'NAME':<24} {'TYPE'}")
    for v in doc.conversation_variables:
        typer.echo(f"{v.get('name', ''):<24} {v.get('value_type', '')}")


@conv_app.command("remove")
def conv_remove(
    name: str = typer.Argument(...),
    file: Path = typer.Option(Path("dsl.yaml"), "--file", "-f"),
) -> None:
    doc = _load(file)
    before = len(doc.conversation_variables)
    doc.conversation_variables = [v for v in doc.conversation_variables if v.get("name") != name]
    if len(doc.conversation_variables) == before:
        raise DifyCliError(f"Conversation var {name!r} not found")
    dsl_mod.save(file, doc)
    typer.secho(f"Removed conversation var {name!r}", fg=typer.colors.GREEN)
