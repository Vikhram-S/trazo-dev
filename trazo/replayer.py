"""
Trazo.replayer
~~~~~~~~~~~~~~~~~~
Time-travel replay engine.

Given a span from a past run, re-execute the original function with the
exact same inputs. Useful for:
- Debugging a failing span without re-running the entire pipeline
- A/B testing prompts by replaying a span with modified inputs
- Cost estimation by replaying with cheaper models
"""
from __future__ import annotations

import importlib
import inspect
import sys
import time
from typing import Any

from .models import ReplayRequest, Span, SpanStatus
from .storage import StorageEngine
from .tracer import run as pw_run
from .tracer import span as pw_span


class ReplayResult:
    """Result of a time-travel replay execution."""

    def __init__(
        self,
        source_span: Span,
        inputs: dict[str, Any],
        outputs: Any | None,
        error: str | None,
        duration_ms: float,
        new_run_id: str | None,
        new_span_id: str | None,
    ) -> None:
        self.source_span = source_span
        self.inputs = inputs
        self.outputs = outputs
        self.error = error
        self.duration_ms = duration_ms
        self.new_run_id = new_run_id
        self.new_span_id = new_span_id

    @property
    def success(self) -> bool:
        return self.error is None


class Replayer:
    """
    Replays individual spans or entire runs using stored inputs.

    The replayer works by:
    1. Looking up the span in storage to get its original inputs
    2. Finding the callable that produced the span (by qualified name)
    3. Calling it with the original (or overridden) inputs
    4. Recording the new execution as a fresh run
    """

    def __init__(self, storage: StorageEngine) -> None:
        self._storage = storage

    def replay(self, request: ReplayRequest) -> ReplayResult:
        """
        Replay a span.

        Args:
            request: ReplayRequest specifying which span to replay and
                     optional input overrides.

        Returns:
            ReplayResult with the outcome of the replay.
        """
        # Load source span
        source_span = self._storage.get_span(request.source_span_id)
        if source_span is None:
            raise ValueError(
                f"Span '{request.source_span_id}' not found in run '{request.source_run_id}'"
            )

        # Merge inputs
        inputs = dict(source_span.inputs)
        if request.override_inputs:
            inputs.update(request.override_inputs)

        if request.dry_run:
            return ReplayResult(
                source_span=source_span,
                inputs=inputs,
                outputs=None,
                error=None,
                duration_ms=0.0,
                new_run_id=None,
                new_span_id=None,
            )

        # Try to find the callable by qualified name
        fn = self._resolve_callable(source_span.name)

        if fn is None:
            raise ValueError(
                f"Could not resolve callable '{source_span.name}'. "
                "Ensure the module is imported before replaying."
            )

        # Execute the replay in a new traced run
        new_run_id: str | None = None
        new_span_id: str | None = None
        result = None
        error = None
        t0 = time.monotonic()

        try:
            with pw_run(
                name=f"replay:{source_span.name}",
                metadata={
                    "replay": True,
                    "source_run_id": request.source_run_id,
                    "source_span_id": request.source_span_id,
                },
            ) as r:
                new_run_id = r.run_id
                with pw_span(
                    f"replay:{source_span.name}",
                    inputs=inputs,
                    tags={"replay": "true"},
                ) as s:
                    new_span_id = s.span_id
                    # Invoke with keyword arguments from stored inputs
                    sig = inspect.signature(fn)
                    valid_params = set(sig.parameters.keys())
                    call_kwargs = {
                        k: v for k, v in inputs.items() if k in valid_params
                    }
                    result = fn(**call_kwargs)
                    s.set_output({"return": result})
        except Exception as exc:
            error = str(exc)

        duration_ms = (time.monotonic() - t0) * 1000

        return ReplayResult(
            source_span=source_span,
            inputs=inputs,
            outputs=result,
            error=error,
            duration_ms=duration_ms,
            new_run_id=new_run_id,
            new_span_id=new_span_id,
        )

    def _resolve_callable(self, qualified_name: str) -> Any:
        """
        Attempt to resolve a callable from its __qualname__ string.
        Searches all currently loaded modules.
        """
        # Try direct attribute lookup across loaded modules
        for mod in list(sys.modules.values()):
            if mod is None:
                continue
            try:
                obj = _get_nested_attr(mod, qualified_name)
                if callable(obj):
                    return obj
            except AttributeError:
                continue
        return None


def _get_nested_attr(obj: Any, path: str) -> Any:
    """Traverse nested attributes using dot/angle-bracket notation."""
    # __qualname__ uses '<locals>' for closures — handle gracefully
    parts = path.replace("<locals>.", "").split(".")
    for part in parts:
        obj = getattr(obj, part)
    return obj
