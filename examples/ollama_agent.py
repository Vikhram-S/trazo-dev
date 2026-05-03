"""
examples/ollama_agent.py
~~~~~~~~~~~~~~~~~~~~~~~~
Demonstrates 100% local, API-free LLM tracing using Ollama.

Requirements:
    1. Install ollama CLI and start it: `ollama serve`
    2. Pull a small model: `ollama pull phi3`
    3. Install the python client: `pip install ollama`

Run:
    python examples/ollama_agent.py
    trazo view
"""
from __future__ import annotations

import os
import sys

# Add project root to path for local development
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import trazo as tz

# 1. Initialize Trazo
tz.init()

try:
    import ollama
except ImportError:
    print("Please install the Ollama python SDK: pip install ollama")
    sys.exit(1)

# 2. Patch Ollama for automatic tracing
tz.instrument_ollama()

@tz.trace(name="local_summarizer", tags={"domain": "research"})
def summarize_text(text: str) -> str:
    """Uses a local Ollama model to summarize text."""
    prompt = f"Summarize this concisely:\n\n{text}"
    
    with tz.span("ollama_call", inputs={"model": "phi3"}) as s:
        print(f"Calling local model 'phi3'...")
        response = ollama.generate(model="phi3", prompt=prompt)
        
        # We can explicitly record custom outputs alongside the auto-captured ones
        s.set_output({"total_duration_ns": response.get("total_duration", 0)})
        
    return response.get("response", "").strip()

if __name__ == "__main__":
    from rich.console import Console
    console = Console()

    console.print("[bold cyan]Trazo + Ollama[/] — 100% Local Execution Tracing\n")
    
    sample_text = (
        "Trazo is an execution tracer for LLM agents that requires zero external dependencies. "
        "It stores all traces locally using SQLite and computes semantic drift locally without ML models. "
        "By integrating natively with Ollama, developers can build robust AI pipelines completely offline "
        "and track their execution, latency, and tokens for free."
    )
    
    try:
        # Check if ollama is running locally
        ollama.list()
    except Exception:
        console.print("[bold red]Error:[/] Ollama is not running locally. Please start `ollama serve`.")
        sys.exit(1)

    with tz.run("local_ollama_pipeline") as r:
        console.print(f"Summarizing text ({len(sample_text)} chars)...")
        summary = summarize_text(sample_text)
        
        console.print(f"\n[bold green]Summary:[/]\n{summary}\n")
        console.print(f"Run ID: [cyan]{r.run_id}[/]")

    # Wait for background flush
    from trazo.collector import get_collector
    get_collector().flush(timeout=3.0)

    console.print("\n[dim]Try: trazo view · trazo ui[/dim]\n")
