from __future__ import annotations

from pathlib import Path

import typer

from ..core import dsl as dsl_mod
from ..core.errors import DifyCliError
from ..core.schema_store import available_versions


def init(
    mode: str = typer.Option(..., "--mode", "-m", help="App mode: workflow|advanced-chat|chat|completion|agent-chat"),
    name: str = typer.Option(..., "--name", "-n", help="App name"),
    output: Path = typer.Option(Path("dsl.yaml"), "--output", "-o", help="Output YAML path"),
    dsl_version: str = typer.Option(dsl_mod.DEFAULT_DSL_VERSION, "--dsl-version", help="DSL version to stamp"),
    description: str = typer.Option("", "--description", "-d", help="App description"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing file"),
) -> None:
    """Scaffold a new Dify DSL file."""
    available = available_versions()
    if dsl_version not in available:
        raise DifyCliError(
            f"DSL version {dsl_version!r} has no schema bundle. Available: {', '.join(available) or 'none'}"
        )
    if output.exists() and not force:
        raise DifyCliError(f"{output} already exists; pass --force to overwrite")
    doc = dsl_mod.init_skeleton(mode=mode, name=name, dsl_version=dsl_version, description=description)
    dsl_mod.save(output, doc)
    typer.secho(f"Created {output} (mode={mode}, dsl_version={dsl_version})", fg=typer.colors.GREEN)
