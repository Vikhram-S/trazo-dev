"""
pw export — Export runs to JSON or standalone HTML reports.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command()
@click.argument("run_id")
@click.option("--format", "fmt", type=click.Choice(["json", "html"]), default="json", show_default=True)
@click.option("--out", "-o", default=None, help="Output file path (default: stdout for JSON).")
@click.option("--db", default=None, help="Path to traces.db.")
def export_cmd(run_id: str, fmt: str, out: str | None, db: str | None) -> None:
    """
    Export a run to JSON or a self-contained HTML report.

    \b
    Examples:
      pw export abc123 --format json > run.json
      pw export abc123 --format html --out report.html
    """
    from ...storage import StorageEngine

    storage = StorageEngine(db_path=db)
    runs = storage.list_runs(limit=1000)
    matched = [r for r in runs if r.run_id.startswith(run_id)]

    if not matched:
        console.print(f"[red]✗ Run not found: {run_id}[/red]")
        raise SystemExit(1)

    run = matched[0]
    spans = storage.get_spans_for_run(run.run_id)

    if fmt == "json":
        payload = {
            "run": run.model_dump(),
            "spans": [s.model_dump() for s in spans],
        }
        content = json.dumps(payload, indent=2, default=str)
        if out:
            Path(out).write_text(content, encoding="utf-8")
            console.print(f"[green]✓ Exported to {out}[/green]")
        else:
            print(content)

    elif fmt == "html":
        content = _render_html(run, spans)
        target = out or f"Trazo_run_{run.run_id[:8]}.html"
        Path(target).write_text(content, encoding="utf-8")
        console.print(f"[green]✓ HTML report written to [bold]{target}[/bold][/green]")
        console.print(f"[dim]Open with: [cyan]open {target}[/cyan][/dim]")


def _render_html(run: object, spans: list) -> str:
    """Generate a self-contained HTML report for a run."""
    import datetime

    run_dict = run.model_dump()  # type: ignore[attr-defined]
    spans_data = [s.model_dump() for s in spans]

    started = datetime.datetime.fromtimestamp(run_dict["started_at"]).strftime("%Y-%m-%d %H:%M:%S")
    duration = f"{run.duration_ms:.0f}ms" if run.duration_ms else "—"  # type: ignore[attr-defined]

    spans_json = json.dumps(spans_data, indent=2, default=str)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Trazo Run: {run_dict['name']}</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --purple: #bc8cff;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; padding: 2rem; }}
  h1 {{ color: var(--accent); font-size: 1.6rem; margin-bottom: .25rem; }}
  .meta {{ color: var(--muted); font-size: .85rem; margin-bottom: 2rem; }}
  .stats {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 2rem; }}
  .stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: .75rem 1.25rem; }}
  .stat-label {{ font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }}
  .stat-value {{ font-size: 1.2rem; font-weight: 700; color: var(--accent); }}
  .span-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: .75rem; cursor: pointer; transition: border-color .2s; }}
  .span-card:hover {{ border-color: var(--accent); }}
  .span-header {{ display: flex; align-items: center; gap: 1rem; }}
  .span-name {{ font-weight: 600; }}
  .badge {{ font-size: .7rem; padding: .2rem .5rem; border-radius: 4px; font-weight: 600; }}
  .badge-ok {{ background: #1a4d2e; color: var(--green); }}
  .badge-error {{ background: #4d1a1a; color: var(--red); }}
  .badge-running {{ background: #4d3e1a; color: var(--yellow); }}
  .span-meta {{ font-size: .8rem; color: var(--muted); display: flex; gap: 1rem; margin-top: .4rem; }}
  .span-body {{ display: none; margin-top: 1rem; border-top: 1px solid var(--border); padding-top: 1rem; }}
  .span-body.open {{ display: block; }}
  pre {{ background: #0d1117; border-radius: 6px; padding: .75rem; font-size: .78rem; overflow-x: auto; border: 1px solid var(--border); white-space: pre-wrap; word-break: break-word; }}
  .label {{ font-size: .75rem; color: var(--muted); text-transform: uppercase; margin-bottom: .25rem; }}
  footer {{ margin-top: 3rem; text-align: center; color: var(--muted); font-size: .8rem; }}
  a {{ color: var(--accent); text-decoration: none; }}
</style>
</head>
<body>
<h1>🧵 {run_dict['name']}</h1>
<div class="meta">Run ID: {run_dict['run_id']} · Started: {started}</div>

<div class="stats">
  <div class="stat"><div class="stat-label">Status</div><div class="stat-value" style="color:{'var(--green)' if run_dict['status']=='ok' else 'var(--red)'}">{run_dict['status'].upper()}</div></div>
  <div class="stat"><div class="stat-label">Duration</div><div class="stat-value">{duration}</div></div>
  <div class="stat"><div class="stat-label">Spans</div><div class="stat-value">{run_dict['span_count']}</div></div>
  <div class="stat"><div class="stat-label">Total Tokens</div><div class="stat-value">{run_dict['total_tokens_in'] + run_dict['total_tokens_out']:,}</div></div>
  <div class="stat"><div class="stat-label">Cost (USD)</div><div class="stat-value">${run_dict['total_cost_usd']:.6f}</div></div>
</div>

<h2 style="margin-bottom:1rem; color:var(--purple)">Execution Spans</h2>
<div id="spans"></div>

<footer>Generated by <a href="https://github.com/trazo-dev/trazo">Trazo</a></footer>

<script>
const spans = {spans_json};

function badge(status) {{
  const cls = {{'ok':'badge-ok','error':'badge-error','running':'badge-running'}}[status] || '';
  return `<span class="badge ${{cls}}">${{status}}</span>`;
}}

const container = document.getElementById('spans');
spans.forEach((s, i) => {{
  const dur = s.ended_at && s.started_at ? ((s.ended_at - s.started_at)*1000).toFixed(0)+'ms' : '—';
  const tokens = (s.tokens_in||0)+(s.tokens_out||0);
  const cost = s.cost_usd ? '$'+s.cost_usd.toFixed(5) : '';
  const indent = s.parent_span_id ? 'margin-left:1.5rem;' : '';
  const div = document.createElement('div');
  div.className = 'span-card';
  div.style = indent;
  div.innerHTML = `
    <div class="span-header">
      ${{badge(s.status)}}
      <span class="span-name">${{s.name}}</span>
      ${{s.model ? `<code style="font-size:.75rem;color:var(--accent)">${{s.model}}</code>` : ''}}
    </div>
    <div class="span-meta">
      <span>⏱ ${{dur}}</span>
      ${{tokens ? `<span>🔤 ${{tokens.toLocaleString()}} tokens</span>` : ''}}
      ${{cost ? `<span>💰 ${{cost}}</span>` : ''}}
      <span style="font-size:.7rem;color:var(--muted)">${{s.span_id.substring(0,8)}}…</span>
    </div>
    <div class="span-body" id="body-${{i}}">
      <div class="label">Inputs</div>
      <pre>${{JSON.stringify(s.inputs, null, 2).substring(0,2000)}}</pre>
      ${{s.outputs ? `<div class="label" style="margin-top:.75rem">Outputs</div><pre>${{JSON.stringify(s.outputs, null, 2).substring(0,2000)}}</pre>` : ''}}
      ${{s.error ? `<div class="label" style="margin-top:.75rem;color:var(--red)">Error</div><pre style="color:var(--red)">${{s.error.substring(0,1000)}}</pre>` : ''}}
    </div>
  `;
  div.addEventListener('click', () => {{
    const body = document.getElementById('body-'+i);
    body.classList.toggle('open');
  }});
  container.appendChild(div);
}});
</script>
</body>
</html>"""
