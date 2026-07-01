from __future__ import annotations

import typer

from .__version__ import __version__
from .commands import edge, init, node, validate, var, version

app = typer.Typer(
    name="dify-cli",
    help="Author Dify DSL (workflow / chatflow) YAML files from the command line.",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
)


@app.callback()
def _main(
    version_flag: bool = typer.Option(
        False, "--version",
        help="Show CLI version and exit (same as `dify-cli version`).",
        is_eager=True,
    ),
) -> None:
    if version_flag:
        typer.echo(f"dify-cli {__version__}")
        raise typer.Exit()


app.command(name="init")(init.init)
app.command(name="validate")(validate.validate)
app.command(name="version")(version.version)
app.add_typer(node.app, name="node")
app.add_typer(edge.app, name="edge")
app.add_typer(var.app, name="var")


if __name__ == "__main__":
    app()
