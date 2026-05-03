"""
Trazo.collector
~~~~~~~~~~~~~~~~~~~
Global TraceCollector singleton — the central hub for all span events.

Design goals:
- Thread-safe: can be called from multiple threads/async contexts simultaneously
- Non-blocking: agents should never wait for storage I/O
- Pluggable: supports multiple storage backends
"""
from __future__ import annotations

import atexit
import queue
import threading
import time
from typing import Any

from .models import Run, Span, SpanStatus
from .storage import StorageEngine

# Sentinel to signal the flush worker to stop
_STOP = object()


class TraceCollector:
    """
    Singleton responsible for receiving trace events and persisting them.

    Architecture:
    - A background thread drains an in-memory queue into the storage engine
    - The main thread never blocks on I/O; it only enqueues events
    - Graceful shutdown: atexit handler drains the queue before process exit
    """

    _instance: TraceCollector | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> TraceCollector:
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._storage: StorageEngine | None = None
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=10_000)
        self._worker: threading.Thread | None = None
        self._enabled: bool = True
        atexit.register(self._shutdown)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def configure(self, storage: StorageEngine) -> None:
        """Set the storage backend and start the flush worker."""
        self._storage = storage
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._flush_loop,
                name="Trazo-flush",
                daemon=True,
            )
            self._worker.start()

    def _flush_loop(self) -> None:
        """Background thread: drain the queue and persist events."""
        while True:
            try:
                item = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if item is _STOP:
                break

            event_type, payload = item
            try:
                if self._storage is None:
                    continue
                if event_type == "span":
                    self._storage.upsert_span(payload)
                elif event_type == "run":
                    self._storage.upsert_run(payload)
                elif event_type == "run_finish":
                    self._storage.refresh_run_aggregates(payload)
            except Exception:
                pass  # Never crash the flush worker

    def _shutdown(self) -> None:
        """Drain remaining events and stop the worker gracefully."""
        self._queue.put_nowait(_STOP)
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=5.0)

    # ------------------------------------------------------------------
    # Event ingestion
    # ------------------------------------------------------------------

    def emit_span(self, span: Span) -> None:
        if not self._enabled or self._storage is None:
            return
        try:
            self._queue.put_nowait(("span", span))
        except queue.Full:
            pass  # Drop silently under extreme load

    def emit_run(self, run: Run) -> None:
        if not self._enabled or self._storage is None:
            return
        try:
            self._queue.put_nowait(("run", run))
        except queue.Full:
            pass

    def finish_run(self, run_id: str) -> None:
        if not self._enabled or self._storage is None:
            return
        try:
            self._queue.put_nowait(("run_finish", run_id))
        except queue.Full:
            pass

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def storage(self) -> StorageEngine | None:
        return self._storage

    def flush(self, timeout: float = 2.0) -> None:
        """Block until the queue is drained (useful in tests)."""
        deadline = time.monotonic() + timeout
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.01)


# Module-level singleton
_collector = TraceCollector()


def get_collector() -> TraceCollector:
    return _collector
