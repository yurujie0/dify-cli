from __future__ import annotations

import typer

from ..__version__ import __version__
from ..core.schema_store import available_versions


def version() -> None:
    """Print CLI version and bundled DSL schema versions."""
    typer.echo(f"dify-cli {__version__}")
    bundled = available_versions()
    if bundled:
        typer.echo(f"Bundled DSL schemas: {', '.join(bundled)}")
    else:
        typer.echo("Bundled DSL schemas: none")
