"""
Trazo.ui.app
~~~~~~~~~~~~~~~~
Lightweight FastAPI web UI for exploring traces visually.
Served locally — no cloud, no external dependencies beyond FastAPI + Jinja2.
"""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError:
    FastAPI = Request = HTMLResponse = JSONResponse = StaticFiles = Jinja2Templates = None  # type: ignore

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def start_server(
    host: str = "127.0.0.1",
    port: int = 7432,
    db_path: str | None = None,
) -> None:
    """Start the Trazo web UI server and open the browser."""
    try:
        import uvicorn  # type: ignore[import]
    except ImportError:
        from rich.console import Console
        Console().print(
            "[red]uvicorn not installed. Run:[/red] [bold cyan]pip install trazo-dev[ui][/bold cyan]"
        )
        return

    app = _build_app(db_path=db_path)
    url = f"http://{host}:{port}"

    from rich.console import Console
    Console().print(f"\n[bold cyan]🧵 Trazo UI[/bold cyan]  →  [link={url}]{url}[/link]\n[dim]Press Ctrl+C to stop.[/dim]\n")

    webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="error")


def _build_app(db_path: str | None = None) -> "Any":
    from ..storage import StorageEngine
    from ..differ import diff_runs

    storage = StorageEngine(db_path=db_path)

    app = FastAPI(title="Trazo UI", docs_url=None, redoc_url=None)

    # Mount static files if directory exists
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        runs = storage.list_runs(limit=100)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"runs": runs},
        )

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
        run = storage.get_run(run_id)
        if not run:
            return HTMLResponse("<h1>Run not found</h1>", status_code=404)
        spans = storage.get_spans_for_run(run_id)
        return templates.TemplateResponse(
            request=request,
            name="run_detail.html",
            context={"run": run, "spans": spans},
        )

    # ------------------------------------------------------------------
    # JSON API (consumed by D3.js frontend)
    # ------------------------------------------------------------------

    @app.get("/api/runs")
    async def api_runs(limit: int = 50) -> JSONResponse:
        runs = storage.list_runs(limit=limit)
        return JSONResponse([r.model_dump() for r in runs])

    @app.get("/api/runs/{run_id}")
    async def api_run(run_id: str) -> JSONResponse:
        run = storage.get_run(run_id)
        if not run:
            return JSONResponse({"error": "not found"}, status_code=404)
        spans = storage.get_spans_for_run(run_id)
        return JSONResponse({
            "run": run.model_dump(),
            "spans": [s.model_dump() for s in spans],
        })

    @app.get("/api/diff/{run_a_id}/{run_b_id}")
    async def api_diff(run_a_id: str, run_b_id: str) -> JSONResponse:
        run_a = storage.get_run(run_a_id)
        run_b = storage.get_run(run_b_id)
        if not run_a or not run_b:
            return JSONResponse({"error": "one or both runs not found"}, status_code=404)
        result = diff_runs(run_a, run_b, storage)
        return JSONResponse(result.model_dump())

    @app.get("/api/stats")
    async def api_stats() -> JSONResponse:
        runs = storage.list_runs(limit=10_000)
        total_cost = sum(r.total_cost_usd for r in runs)
        total_tokens = sum(r.total_tokens for r in runs)
        return JSONResponse({
            "run_count": len(runs),
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "db_path": str(storage.db_path),
        })

    return app
