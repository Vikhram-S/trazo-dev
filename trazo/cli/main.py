"""
Trazo.cli.main
~~~~~~~~~~~~~~~~~~
Click-based CLI entrypoint for the `pw` command.
"""

from __future__ import annotations

import click
from rich.console import Console

from .commands.clean import clean_cmd
from .commands.diff import diff_cmd
from .commands.export import export_cmd
from .commands.replay import replay_cmd
from .commands.view import view_cmd

console = Console()


@click.group()
@click.version_option(package_name="trazo")
def cli() -> None:
    """
    \b
    ___________ ____  ___   __________ 
   /_  __/ __ \/   | /   | /___  / __ \
    / / / /_/ / /| |/ /| |    / / / / /
   / / / _, _/ ___ / ___ |  / / /_/ / 
  /_/ /_/ |_/_/  |_/_/  |_/____/\____/ 

    Trazo - Execution tracer & semantic diff for LLM agents.
    """


# CLI registration
cli.add_command(view_cmd, name="view")
cli.add_command(diff_cmd, name="diff")
cli.add_command(replay_cmd, name="replay")
cli.add_command(export_cmd, name="export")
cli.add_command(clean_cmd, name="clean")


@cli.command("ui")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to.")
@click.option("--port", default=7432, show_default=True, help="Port to listen on.")
@click.option("--db", default=None, help="Path to traces.db (default: ~/.trazo/traces.db).")
def ui_cmd(host: str, port: int, db: str | None) -> None:
    """Launch the Trazo web UI in your browser."""
    from ..ui.app import start_server

    start_server(host=host, port=port, db_path=db)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
