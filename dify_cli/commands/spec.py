from __future__ import annotations

import json
from pathlib import Path

import typer

from ..core.errors import DifyCliError
from ..core.spec_validator import validate_spec

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Validate a workflow spec before applying it.")


@app.command("validate")
def validate(
    spec: Path = typer.Option(..., "--spec", "-s", help="Path to the workflow spec JSON file"),
) -> None:
    """Check a spec's variable references and scope. Run this in the design
    stage and fix errors before `dify-cli apply`."""
    if not spec.exists():
        raise DifyCliError(f"Spec file not found: {spec}")
    try:
        spec_data = json.loads(spec.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DifyCliError(f"Invalid JSON in spec {spec}: {e}") from e

    errors = validate_spec(spec_data)
    if errors:
        for e in errors:
            typer.secho(f"FAIL {e}", fg=typer.colors.RED)
        typer.secho(f"\n{len(errors)} error(s). Fix the spec and re-validate.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    node_count = len(spec_data.get("nodes", []))
    typer.secho(f"OK spec is valid ({node_count} nodes)", fg=typer.colors.GREEN)
