"""
trazo diff <run_a> <run_b> — Semantic diff between two runs.
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()


@click.command()
@click.argument("run_a")
@click.argument("run_b")
@click.option("--db", default=None, help="Path to traces.db.")
@click.option("--show-identical", is_flag=True, default=False, help="Also show identical spans.")
def diff_cmd(run_a: str, run_b: str, db: str | None, show_identical: bool) -> None:
    """
    Semantic diff between two pipeline runs.

    Compares inputs, outputs, cost, latency, and token usage
    across matched spans. Highlights what changed and by how much.

    \b
    Examples:
      trazo diff abc123 def456
      trazo diff abc123 def456 --show-identical
    """
    from ...storage import StorageEngine
    from ...differ import diff_runs
    from ...models import DiffKind

    storage = StorageEngine(db_path=db)

    run_a_obj = _resolve_run(storage, run_a)
    run_b_obj = _resolve_run(storage, run_b)

    console.print()
    console.print(Panel(
        f"[dim]Comparing[/dim] [bold cyan]{run_a_obj.name}[/bold cyan] [dim]({run_a_obj.run_id[:8]}…)[/dim]\n"
        f"[dim]against  [/dim] [bold magenta]{run_b_obj.name}[/bold magenta] [dim]({run_b_obj.run_id[:8]}…)[/dim]",
        title="[bold]Semantic Diff[/bold]",
        border_style="cyan",
    ))

    result = diff_runs(run_a_obj, run_b_obj, storage)

    # Overall similarity banner
    sim_pct = result.overall_similarity * 100
    if sim_pct >= 97:
        sim_color = "green"
        verdict = "Virtually identical"
    elif sim_pct >= 65:
        sim_color = "yellow"
        verdict = "Similar with changes"
    else:
        sim_color = "red"
        verdict = "Significant divergence"

    console.print(f"\n[bold]Overall similarity:[/bold] [{sim_color}]{sim_pct:.1f}%[/{sim_color}]  [dim]— {verdict}[/dim]")

    # Aggregate deltas
    cost_sign = "+" if result.cost_delta_usd >= 0 else ""
    token_sign = "+" if result.token_delta >= 0 else ""
    lat_sign = "+" if result.latency_delta_ms >= 0 else ""
    console.print(
        f"[dim]Cost delta:[/dim]    [{_delta_color(result.cost_delta_usd)}]{cost_sign}${result.cost_delta_usd:.6f}[/]\n"
        f"[dim]Token delta:[/dim]   [{_delta_color(result.token_delta)}]{token_sign}{result.token_delta:,}[/]\n"
        f"[dim]Latency delta:[/dim] [{_delta_color(result.latency_delta_ms)}]{lat_sign}{result.latency_delta_ms:.0f}ms[/]"
    )

    # Per-span diff table
    diffs = result.span_diffs
    if not show_identical:
        diffs = [d for d in diffs if d.kind != DiffKind.IDENTICAL]

    if not diffs:
        console.print("\n[bold green]✓ All spans are identical.[/bold green]\n")
        return

    table = Table(
        title=f"\n[bold]Span Changes[/bold] ({len(result.changed_spans)} changed)",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold magenta",
        show_header=True,
    )
    table.add_column("Span", style="white", min_width=25)
    table.add_column("Kind", justify="center", width=12)
    table.add_column("Similarity", justify="right", width=11)
    table.add_column("Cost Δ", justify="right", width=12)
    table.add_column("Token Δ", justify="right", width=10)
    table.add_column("Latency Δ", justify="right", width=11)

    for d in diffs:
        kind_text = _kind_badge(d.kind.value)
        sim = f"{d.similarity_score * 100:.1f}%"
        cost_d = f"+${d.cost_delta_usd:.5f}" if d.cost_delta_usd and d.cost_delta_usd > 0 else (f"-${abs(d.cost_delta_usd):.5f}" if d.cost_delta_usd else "—")
        tok_d = f"+{d.token_delta:,}" if d.token_delta and d.token_delta > 0 else (str(d.token_delta) if d.token_delta else "—")
        lat_d = f"+{d.latency_delta_ms:.0f}ms" if d.latency_delta_ms and d.latency_delta_ms > 0 else (f"{d.latency_delta_ms:.0f}ms" if d.latency_delta_ms else "—")

        table.add_row(
            d.span_name,
            kind_text,
            sim,
            cost_d,
            tok_d,
            lat_d,
        )

    console.print(table)

    # Show output diffs for diverged spans
    from ...models import DiffKind as DK
    diverged = [d for d in result.changed_spans if d.kind in (DK.DIVERGED, DK.SIMILAR)]
    if diverged:
        console.print("\n[bold magenta]Output Changes[/bold magenta]\n")
        for d in diverged[:5]:  # Cap at 5 to avoid terminal flooding
            console.print(f"[bold]{d.span_name}[/bold]")
            _print_side_by_side(
                d.run_a_output or "[dim]no output[/dim]",
                d.run_b_output or "[dim]no output[/dim]",
            )
            console.print()

    console.print(
        f"[dim]Use [bold cyan]trazo view {run_b[:8]}[/bold cyan] for the full span tree.[/dim]\n"
    )


def _resolve_run(storage: "object", run_id: str) -> "object":
    runs = storage.list_runs(limit=1000)
    matched = [r for r in runs if r.run_id.startswith(run_id)]
    if not matched:
        console.print(f"[red]Run not found: {run_id}[/red]")
        raise SystemExit(1)
    return matched[0]


def _kind_badge(kind: str) -> str:
    mapping = {
        "identical": "[bold green]≡ identical[/bold green]",
        "similar":   "[bold yellow]≈ similar[/bold yellow]",
        "diverged":  "[bold red]≠ diverged[/bold red]",
        "added":     "[bold cyan]+ added[/bold cyan]",
        "removed":   "[bold dim]- removed[/bold dim]",
    }
    return mapping.get(kind, kind)


def _delta_color(val: float | int | None) -> str:
    if val is None:
        return "dim"
    if val > 0:
        return "red"
    if val < 0:
        return "green"
    return "dim"


def _print_side_by_side(left: str, right: str, max_width: int = 60) -> None:
    """Print two text blocks side by side with a separator."""
    left_lines = (left or "")[:1000].split("\n")[:8]
    right_lines = (right or "")[:1000].split("\n")[:8]
    max_lines = max(len(left_lines), len(right_lines))
    left_lines += [""] * (max_lines - len(left_lines))
    right_lines += [""] * (max_lines - len(right_lines))

    console.print(f"  [cyan]{'Run A':<{max_width}}[/cyan]  [magenta]Run B[/magenta]")
    console.print(f"  {'─' * max_width}  {'─' * max_width}")
    for l_line, r_line in zip(left_lines, right_lines):
        l_trunc = l_line[:max_width].ljust(max_width)
        r_trunc = r_line[:max_width]
        console.print(f"  [dim]{l_trunc}[/dim]  [white]{r_trunc}[/white]")
