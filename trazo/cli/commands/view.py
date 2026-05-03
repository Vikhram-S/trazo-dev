"""
trazo view — List and inspect traced runs in the terminal.
"""

from __future__ import annotations

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from ...storage import StorageEngine

console = Console()


@click.command()
@click.argument("run_id", required=False)
@click.option("--db", default=None, help="Path to traces.db.")
@click.option("--limit", default=20, show_default=True, help="Max runs to list.")
@click.option("--spans", is_flag=True, default=False, help="Show all spans for a run.")
def view_cmd(run_id: str | None, db: str | None, limit: int, spans: bool) -> None:
    """
    List recent runs or inspect a specific run.

    \b
    Examples:
      trazo view                     # list last 20 runs
      trazo view abc123              # inspect run abc123
      trazo view abc123 --spans      # show full span tree
    """
    from ...storage import StorageEngine

    storage = StorageEngine(db_path=db)

    if run_id is None:
        _list_runs(storage, limit)
    else:
        _inspect_run(storage, run_id, show_spans=spans)


# ---------------------------------------------------------------------------
# List view
# ---------------------------------------------------------------------------


def _list_runs(storage: StorageEngine, limit: int) -> None:
    runs = storage.list_runs(limit=limit)

    if not runs:
        console.print(
            Panel(
                "[dim]No runs found. Instrument your code with\n"
                "[bold cyan]@tz.trace[/] and run it.[/dim]",
                title="[bold]Trazo[/bold]",
                border_style="cyan",
            )
        )
        return

    table = Table(
        title="[bold cyan]Recent Runs[/bold cyan]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        border_style="cyan",
        row_styles=["none", "dim"],
    )
    table.add_column("Run ID", style="cyan", no_wrap=True, width=12)
    table.add_column("Name", style="white", min_width=20)
    table.add_column("Status", justify="center", width=9)
    table.add_column("Spans", justify="right", width=6)
    table.add_column("Tokens", justify="right", width=10)
    table.add_column("Cost (USD)", justify="right", width=10)
    table.add_column("Duration", justify="right", width=10)
    table.add_column("Started", width=20)

    import datetime

    for r in runs:
        status_text = _status_badge(r.status.value)
        duration = f"{r.duration_ms:.0f}ms" if r.duration_ms else "—"
        cost = f"${r.total_cost_usd:.4f}" if r.total_cost_usd else "—"
        tokens = f"{r.total_tokens:,}" if r.total_tokens else "—"
        started = datetime.datetime.fromtimestamp(r.started_at).strftime("%m-%d %H:%M:%S")

        table.add_row(
            r.run_id[:8] + "…",
            r.name,
            status_text,
            str(r.span_count),
            tokens,
            cost,
            duration,
            started,
        )

    console.print()
    console.print(table)
    console.print(
        f"\n[dim]Showing {len(runs)} of most recent runs. "
        "Use [bold cyan]trazo view <run_id>[/bold cyan] to inspect a run.[/dim]\n"
    )


# ---------------------------------------------------------------------------
# Detail / span tree view
# ---------------------------------------------------------------------------


def _inspect_run(storage: StorageEngine, run_id: str, show_spans: bool) -> None:
    # Support short IDs (prefix matching)
    all_runs = storage.list_runs(limit=1000)
    matched = [r for r in all_runs if r.run_id.startswith(run_id)]

    if not matched:
        console.print(f"[red]✗ No run found matching '[bold]{run_id}[/bold]'[/red]")
        raise SystemExit(1)
    if len(matched) > 1:
        console.print(
            f"[yellow]Ambiguous run ID prefix. Matches: {[r.run_id for r in matched]}[/yellow]"
        )
        raise SystemExit(1)

    run = matched[0]

    import datetime

    started_dt = datetime.datetime.fromtimestamp(run.started_at).strftime("%Y-%m-%d %H:%M:%S")

    # Header panel
    info_lines = [
        f"[bold cyan]Run ID:[/bold cyan]    {run.run_id}",
        f"[bold cyan]Name:[/bold cyan]      {run.name}",
        f"[bold cyan]Status:[/bold cyan]    {_status_badge(run.status.value)}",
        f"[bold cyan]Started:[/bold cyan]   {started_dt}",
        f"[bold cyan]Duration:[/bold cyan]  {run.duration_ms:.0f}ms"
        if run.duration_ms
        else "[bold cyan]Duration:[/bold cyan]  running…",
        f"[bold cyan]Spans:[/bold cyan]     {run.span_count}",
        f"[bold cyan]Tokens:[/bold cyan]    {run.total_tokens:,}  "
        f"[dim]({run.total_tokens_in:,} in / {run.total_tokens_out:,} out)[/dim]",
        f"[bold cyan]Cost:[/bold cyan]      ${run.total_cost_usd:.6f}",
    ]
    if run.metadata:
        info_lines.append(f"[bold cyan]Metadata:[/bold cyan] {run.metadata}")

    console.print()
    console.print(
        Panel(
            "\n".join(info_lines),
            title=f"[bold]Run: {run.name}[/bold]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    # Span tree
    spans = storage.get_spans_for_run(run.run_id)
    if not spans:
        console.print("[dim]No spans recorded.[/dim]\n")
        return

    console.print(f"\n[bold magenta]Execution Tree[/bold magenta] ({len(spans)} spans)\n")
    _render_span_tree(spans, show_full=show_spans)
    console.print()


def _render_span_tree(spans: list, show_full: bool = False) -> None:
    """Render spans as a rich tree, respecting parent-child relationships."""
    from rich.tree import Tree

    span_map = {s.span_id: s for s in spans}
    roots = [s for s in spans if s.parent_span_id is None or s.parent_span_id not in span_map]

    def add_children(tree_node: Tree, parent_span_id: str) -> None:
        children = [s for s in spans if s.parent_span_id == parent_span_id]
        children.sort(key=lambda s: s.started_at)
        for child in children:
            label = _span_label(child, show_full)
            child_node = tree_node.add(label)
            add_children(child_node, child.span_id)

    for root in roots:
        root_label = _span_label(root, show_full)
        tree = Tree(root_label)
        add_children(tree, root.span_id)
        console.print(tree)


def _span_label(span: object, show_full: bool) -> str:
    name = getattr(span, "name", "?")
    status = getattr(span, "status", None)
    duration = getattr(span, "duration_ms", None)
    model = getattr(span, "model", None)
    tokens_in = getattr(span, "tokens_in", None)
    tokens_out = getattr(span, "tokens_out", None)
    cost = getattr(span, "cost_usd", None)
    error = getattr(span, "error", None)

    badge = _status_badge(status.value if status else "?")
    parts = [f"{badge} [bold]{name}[/bold]"]

    if model:
        parts.append(f"[dim cyan]{model}[/dim cyan]")
    if duration is not None:
        parts.append(f"[dim]{duration:.0f}ms[/dim]")
    if tokens_in or tokens_out:
        parts.append(f"[dim yellow]{(tokens_in or 0) + (tokens_out or 0):,} tok[/dim yellow]")
    if cost:
        parts.append(f"[dim green]${cost:.5f}[/dim green]")
    if error and show_full:
        parts.append(f"\n  [red]{error[:200]}[/red]")

    return " · ".join(parts)


def _status_badge(status: str) -> str:
    mapping = {
        "ok": "[bold green]✓ ok[/bold green]",
        "error": "[bold red]✗ err[/bold red]",
        "running": "[bold yellow]⟳ run[/bold yellow]",
        "pending": "[dim]○ wait[/dim]",
    }
    return mapping.get(status, f"[dim]{status}[/dim]")
