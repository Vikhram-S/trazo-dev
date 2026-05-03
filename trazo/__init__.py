"""
Trazo
~~~~~
Zero-dependency execution tracer and semantic diff engine for LLM agent pipelines.

Quick start::

    import trazo as tz

    # One-time setup (usually in your app startup)
    tz.init()

    # Instrument your code
    @tz.trace
    def my_agent_step(prompt: str) -> str:
        return call_llm(prompt)

    # Wrap pipeline runs
    with tz.run("my_pipeline"):
        result = my_agent_step("Hello")

    # View traces
    # $ trazo view          # terminal
    # $ trazo ui            # browser DAG

Public API surface:
    tz.init()               — initialize storage
    tz.trace                — decorator
    tz.run()                — run context manager
    tz.span()               — span context manager
    tz.aspan()              — async span context manager
    tz.instrument_openai()  — OpenAI auto-instrumentation
    tz.instrument_ollama()  — Ollama auto-instrumentation (local models)
    tz.get_current_span()   — get active span
    tz.get_current_run()    — get active run
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .collector import TraceCollector, get_collector
from .models import DiffKind, Run, RunDiff, Span, SpanDiff, SpanStatus
from .storage import StorageEngine
from .tracer import (
    RunContext,
    SpanContext,
    aspan,
    get_current_run,
    get_current_span,
    run,
    span,
    trace,
)

__version__ = "0.1.0"
__author__ = "Trazo Contributors"
__license__ = "MIT"

__all__ = [
    # Core API
    "init",
    "trace",
    "run",
    "span",
    "aspan",
    "get_current_span",
    "get_current_run",
    # Instrumentation
    "instrument_openai",
    "instrument_ollama",
    # Models (re-exported for user convenience)
    "Span",
    "Run",
    "RunDiff",
    "SpanDiff",
    "SpanStatus",
    "DiffKind",
    # Version
    "__version__",
]

# Module-level storage instance
_storage: StorageEngine | None = None


def init(
    db_path: str | Path | None = None,
    *,
    auto_instrument_openai: bool = False,
) -> StorageEngine:
    """
    Initialize Trazo. Call this once at application startup.

    Args:
        db_path: Path to the SQLite database file.
                 Defaults to ~/.trazo/traces.db
        auto_instrument_openai: If True, automatically patches the OpenAI SDK.

    Returns:
        The initialized StorageEngine instance.
    """
    global _storage
    _storage = StorageEngine(db_path=db_path)
    collector = get_collector()
    collector.configure(_storage)

    if auto_instrument_openai:
        instrument_openai()

    return _storage


def instrument_openai() -> bool:
    """
    Auto-instrument the OpenAI Python SDK.

    Patches openai.chat.completions.create to automatically create spans
    with token counts, cost estimates, and model metadata.

    Returns True if patching succeeded, False if openai is not installed.
    """
    from .integrations.openai_patch import patch_openai
    return patch_openai()


def get_storage() -> StorageEngine:
    """Get the active storage engine, initializing with defaults if needed."""
    global _storage
    if _storage is None:
        _storage = init()
    return _storage
