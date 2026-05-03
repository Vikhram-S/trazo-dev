"""
trazo replay — Re-execute a span with its original inputs (time-travel replay).
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()


@click.command()
@click.argument("span_id")
@click.option("--run", "run_id", default=None, help="Run ID containing the span.")
@click.option("--db", default=None, help="Path to traces.db.")
@click.option("--dry-run", is_flag=True, default=False, help="Print inputs without executing.")
@click.option("--override", "-o", multiple=True, metavar="KEY=VALUE",
              help="Override an input field, e.g. -o model=gpt-4o-mini")
def replay_cmd(
    span_id: str,
    run_id: str | None,
    db: str | None,
    dry_run: bool,
    override: tuple[str, ...],
) -> None:
    """
    Time-travel replay: re-execute a span with its original inputs.

    Optionally override specific input fields to test variations.

    \b
    Examples:
      trazo replay abc123def456           # replay with original inputs
      trazo replay abc123 --dry-run       # print inputs without running
      trazo replay abc123 -o model=gpt-4o-mini -o temperature=0.2
    """
    import json
    from ...storage import StorageEngine
    from ...replayer import Replayer
    from ...models import ReplayRequest

    storage = StorageEngine(db_path=db)
    replayer = Replayer(storage)

    # Parse overrides
    override_inputs: dict = {}
    for item in override:
        if "=" not in item:
            console.print(f"[red]Invalid override '{item}'. Use KEY=VALUE format.[/red]")
            raise SystemExit(1)
        k, v = item.split("=", 1)
        # Try to parse as JSON; fall back to string
        try:
            override_inputs[k] = json.loads(v)
        except json.JSONDecodeError:
            override_inputs[k] = v

    # Resolve full span_id from prefix
    if run_id:
        spans = storage.get_spans_for_run(run_id)
    else:
        # Search across all recent runs
        runs = storage.list_runs(limit=100)
        spans = []
        for r in runs:
            spans.extend(storage.get_spans_for_run(r.run_id))

    matched = [s for s in spans if s.span_id.startswith(span_id)]
    if not matched:
        console.print(f"[red]✗ No span found matching '{span_id}'[/red]")
        raise SystemExit(1)
    if len(matched) > 1:
        console.print(f"[yellow]Ambiguous span ID. Matches: {[s.span_id for s in matched[:5]]}[/yellow]")
        raise SystemExit(1)

    target = matched[0]

    console.print()
    console.print(Panel(
        f"[bold cyan]Span:[/bold cyan]    {target.name}\n"
        f"[bold cyan]Span ID:[/bold cyan] {target.span_id[:12]}…\n"
        f"[bold cyan]Model:[/bold cyan]   {target.model or 'N/A'}\n"
        f"[bold cyan]Mode:[/bold cyan]    {'[yellow]dry-run[/yellow]' if dry_run else '[green]execute[/green]'}",
        title="[bold]Time-Travel Replay[/bold]",
        border_style="cyan",
    ))

    # Show original inputs
    import json as _json
    console.print("\n[bold magenta]Original Inputs:[/bold magenta]")
    console.print(Syntax(
        _json.dumps(target.inputs, indent=2, default=str)[:2000],
        "json",
        theme="monokai",
        line_numbers=False,
    ))

    if override_inputs:
        console.print("\n[bold yellow]Overrides Applied:[/bold yellow]")
        console.print(Syntax(
            _json.dumps(override_inputs, indent=2)[:1000],
            "json",
            theme="monokai",
        ))

    if dry_run:
        console.print("\n[dim]Dry-run complete. Use without --dry-run to execute.[/dim]\n")
        return

    req = ReplayRequest(
        source_run_id=target.run_id,
        source_span_id=target.span_id,
        override_inputs=override_inputs if override_inputs else None,
        dry_run=False,
    )

    console.print("\n[bold]Executing replay…[/bold]")

    try:
        result = replayer.replay(req)
    except ValueError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise SystemExit(1)

    if result.success:
        console.print(f"[bold green]✓ Replay succeeded[/bold green] in {result.duration_ms:.0f}ms")
        if result.new_run_id:
            console.print(f"[dim]New run: [cyan]{result.new_run_id[:8]}…[/cyan][/dim]")
        if result.outputs is not None:
            console.print("\n[bold magenta]Output:[/bold magenta]")
            console.print(Syntax(
                _json.dumps(result.outputs, indent=2, default=str)[:2000],
                "json",
                theme="monokai",
            ))
    else:
        console.print(f"[bold red]✗ Replay failed:[/bold red] {result.error}")

    console.print()
