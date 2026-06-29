from __future__ import annotations

import typer

from .commands import edge, init, node, validate, var, version

app = typer.Typer(
    name="dify-cli",
    help="Author Dify DSL (workflow / chatflow) YAML files from the command line.",
    no_args_is_help=True,
    add_completion=False,
)

app.command(name="init")(init.init)
app.command(name="validate")(validate.validate)
app.command(name="version")(version.version)
app.add_typer(node.app, name="node")
app.add_typer(edge.app, name="edge")
app.add_typer(var.app, name="var")


if __name__ == "__main__":
    app()
