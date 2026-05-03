"""
Trazo
~~~~~
Zero-dependency execution tracer and semantic diff engine for LLM agent pipelines.
"""

from __future__ import annotations

from pathlib import Path

from .collector import get_collector
from .models import DiffKind, Run, RunDiff, Span, SpanDiff, SpanStatus
from .storage import StorageEngine
from .tracer import (
    aspan,
    get_current_run,
    get_current_span,
    run,
    span,
    trace,
)

__version__ = "0.1.1"
__author__ = "Vikhram S"
__license__ = "MIT"

__all__ = [
    "DiffKind",
    "Run",
    "RunDiff",
    "Span",
    "SpanDiff",
    "SpanStatus",
    "__version__",
    "aspan",
    "get_current_run",
    "get_current_span",
    "init",
    "instrument_ollama",
    "instrument_openai",
    "run",
    "span",
    "trace",
]

# Module-level storage instance
_storage: StorageEngine | None = None


def init(
    db_path: str | Path | None = None,
    *,
    auto_instrument_openai: bool = False,
    auto_instrument_ollama: bool = False,
) -> StorageEngine:
    """
    Initialize Trazo. Call this once at application startup.
    """
    global _storage
    _storage = StorageEngine(db_path=db_path)
    collector = get_collector()
    collector.configure(_storage)

    if auto_instrument_openai:
        instrument_openai()
    if auto_instrument_ollama:
        instrument_ollama()

    return _storage


def instrument_openai() -> bool:
    """Auto-instrument the OpenAI Python SDK."""
    from .integrations.openai_patch import patch_openai

    return patch_openai()


def instrument_ollama() -> bool:
    """Auto-instrument the Ollama Python SDK."""
    from .integrations.ollama_patch import patch_ollama

    return patch_ollama()


def get_storage() -> StorageEngine:
    """Get the active storage engine, initializing with defaults if needed."""
    global _storage
    if _storage is None:
        _storage = init()
    return _storage
