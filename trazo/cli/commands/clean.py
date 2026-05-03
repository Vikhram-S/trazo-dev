"""
pw clean — Delete old runs from the database.
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.prompt import Confirm

console = Console()


@click.command()
@click.option("--older-than", default=None, type=int, metavar="DAYS",
              help="Delete runs older than N days.")
@click.option("--keep", default=None, type=int, metavar="N",
              help="Keep only the N most recent runs, delete the rest.")
@click.option("--run", "run_id", default=None, help="Delete a specific run by ID.")
@click.option("--all", "delete_all", is_flag=True, default=False, help="Delete ALL runs (prompts for confirmation).")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.option("--db", default=None, help="Path to traces.db.")
def clean_cmd(
    older_than: int | None,
    keep: int | None,
    run_id: str | None,
    delete_all: bool,
    yes: bool,
    db: str | None,
) -> None:
    """
    Remove old runs from the trace database.

    \b
    Examples:
      pw clean --older-than 7       # delete runs older than 7 days
      pw clean --keep 50            # keep only the 50 most recent runs
      pw clean --run abc123         # delete a specific run
      pw clean --all --yes          # wipe everything without prompting
    """
    import time
    from ...storage import StorageEngine

    storage = StorageEngine(db_path=db)
    all_runs = storage.list_runs(limit=100_000)

    to_delete: list = []

    if run_id:
        matched = [r for r in all_runs if r.run_id.startswith(run_id)]
        if not matched:
            console.print(f"[red]✗ Run not found: {run_id}[/red]")
            raise SystemExit(1)
        to_delete = matched

    elif delete_all:
        to_delete = all_runs

    elif older_than is not None:
        cutoff = time.time() - (older_than * 86400)
        to_delete = [r for r in all_runs if r.started_at < cutoff]

    elif keep is not None:
        if len(all_runs) > keep:
            to_delete = all_runs[keep:]  # list is already sorted newest-first
    else:
        console.print("[yellow]Specify a clean option. Use --help for details.[/yellow]")
        raise SystemExit(1)

    if not to_delete:
        console.print("[dim]Nothing to delete.[/dim]")
        return

    console.print(f"[bold]About to delete[/bold] [red]{len(to_delete)}[/red] run(s).")

    if not yes:
        confirmed = Confirm.ask("Continue?", default=False)
        if not confirmed:
            console.print("[dim]Cancelled.[/dim]")
            return

    for r in to_delete:
        storage.delete_run(r.run_id)

    console.print(f"[green]✓ Deleted {len(to_delete)} run(s).[/green]")
