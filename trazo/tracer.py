"""
Trazo.tracer
~~~~~~~~~~~~~~~~
The core instrumentation API.

Usage:
    import trazo as tz

    @tz.trace
    def call_llm(prompt: str) -> str:
        ...

    with tz.span("my_step") as s:
        s.set_model("gpt-4o")
        result = do_something()
        s.set_output({"result": result})

    # Context manager for async code
    async with tz.aspan("async_step") as s:
        ...
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import time
import traceback
import uuid
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, TypeVar

from .collector import get_collector
from .models import Run, Span, SpanStatus

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Context variable: current active span (propagated through call stack)
# ---------------------------------------------------------------------------
_current_span: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "Trazo_current_span", default=None
)
_current_run: contextvars.ContextVar[Run | None] = contextvars.ContextVar(
    "Trazo_current_run", default=None
)


def get_current_span() -> Span | None:
    return _current_span.get()


def get_current_run() -> Run | None:
    return _current_run.get()


# ---------------------------------------------------------------------------
# SpanContext — mutable handle for configuring a span mid-flight
# ---------------------------------------------------------------------------


class SpanContext:
    """
    A live handle to an in-progress span.
    Returned by the `span()` context manager.
    """

    def __init__(self, span: Span) -> None:
        self._span = span

    # LLM metadata helpers
    def set_model(self, model: str, provider: str | None = None) -> None:
        self._span.model = model
        if provider:
            self._span.provider = provider

    def set_tokens(self, tokens_in: int, tokens_out: int) -> None:
        self._span.tokens_in = tokens_in
        self._span.tokens_out = tokens_out

    def set_cost(self, cost_usd: float) -> None:
        self._span.cost_usd = cost_usd

    def set_output(self, output: dict[str, Any]) -> None:
        self._span.outputs = output

    def set_input(self, key: str, value: Any) -> None:
        self._span.inputs[key] = value

    def tag(self, key: str, value: str) -> None:
        self._span.tags[key] = value

    @property
    def span_id(self) -> str:
        return self._span.span_id

    @property
    def run_id(self) -> str:
        return self._span.run_id


# ---------------------------------------------------------------------------
# RunContext — represents an active top-level run
# ---------------------------------------------------------------------------


class RunContext:
    """Active run handle returned by tz.run()."""

    def __init__(self, run: Run, _token: Any) -> None:
        self._run = run
        self._token = _token

    def tag(self, key: str, value: Any) -> None:
        self._run.metadata[key] = value

    @property
    def run_id(self) -> str:
        return self._run.run_id

    def __enter__(self) -> RunContext:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._run.ended_at = time.time()
        self._run.status = SpanStatus.ERROR if exc_type else SpanStatus.OK
        collector = get_collector()
        collector.emit_run(self._run)
        collector.finish_run(self._run.run_id)
        _current_run.reset(self._token)


# ---------------------------------------------------------------------------
# Public API: run context manager
# ---------------------------------------------------------------------------


@contextmanager
def run(
    name: str = "unnamed",
    metadata: dict[str, Any] | None = None,
) -> Generator[RunContext, None, None]:
    """
    Context manager for a top-level run.

    Example::
        with tz.run("my_pipeline") as r:
            r.tag("version", "v2")
            result = run_pipeline()
    """
    active_run = Run(
        run_id=str(uuid.uuid4()),
        name=name,
        started_at=time.time(),
        metadata=metadata or {},
    )
    collector = get_collector()
    collector.emit_run(active_run)
    token = _current_run.set(active_run)
    ctx = RunContext(active_run, token)
    try:
        yield ctx
        ctx.__exit__(None, None, None)
    except Exception:
        import sys

        ctx.__exit__(*sys.exc_info())
        raise


# ---------------------------------------------------------------------------
# Public API: span context manager (sync)
# ---------------------------------------------------------------------------


@contextmanager
def span(
    name: str,
    inputs: dict[str, Any] | None = None,
    tags: dict[str, str] | None = None,
) -> Generator[SpanContext, None, None]:
    """
    Context manager for a traced span.

    Example::
        with tz.span("parse_response", inputs={"raw": data}) as s:
            result = parse(data)
            s.set_output({"parsed": result})
    """
    active_run = _current_run.get()
    parent_span = _current_span.get()

    s = Span(
        span_id=str(uuid.uuid4()),
        run_id=active_run.run_id if active_run else "unattached",
        name=name,
        parent_span_id=parent_span.span_id if parent_span else None,
        started_at=time.time(),
        status=SpanStatus.RUNNING,
        inputs=inputs or {},
        tags=tags or {},
    )

    collector = get_collector()
    collector.emit_span(s)

    token = _current_span.set(s)
    ctx = SpanContext(s)

    try:
        yield ctx
        s.status = SpanStatus.OK
    except Exception as exc:
        s.status = SpanStatus.ERROR
        s.error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        raise
    finally:
        s.ended_at = time.time()
        collector.emit_span(s)
        _current_span.reset(token)


# ---------------------------------------------------------------------------
# Public API: async span context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def aspan(
    name: str,
    inputs: dict[str, Any] | None = None,
    tags: dict[str, str] | None = None,
) -> AsyncGenerator[SpanContext, None]:
    """Async version of tz.span()."""
    active_run = _current_run.get()
    parent_span = _current_span.get()

    s = Span(
        span_id=str(uuid.uuid4()),
        run_id=active_run.run_id if active_run else "unattached",
        name=name,
        parent_span_id=parent_span.span_id if parent_span else None,
        started_at=time.time(),
        status=SpanStatus.RUNNING,
        inputs=inputs or {},
        tags=tags or {},
    )

    collector = get_collector()
    collector.emit_span(s)

    token = _current_span.set(s)
    ctx = SpanContext(s)

    try:
        yield ctx
        s.status = SpanStatus.OK
    except Exception as exc:
        s.status = SpanStatus.ERROR
        s.error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        raise
    finally:
        s.ended_at = time.time()
        collector.emit_span(s)
        _current_span.reset(token)


# ---------------------------------------------------------------------------
# Public API: @trace decorator (sync and async)
# ---------------------------------------------------------------------------


def trace(
    func: F | None = None,
    *,
    name: str | None = None,
    capture_inputs: bool = True,
    capture_output: bool = True,
    tags: dict[str, str] | None = None,
) -> F:
    """
    Decorator to automatically trace a function.

    Supports both sync and async functions.

    Example::
        @tz.trace
        def call_llm(prompt: str) -> str:
            ...

        @tz.trace(name="custom_name", tags={"tier": "llm"})
        async def async_call(msg: str) -> dict:
            ...
    """

    def decorator(fn: F) -> F:
        span_name = name or fn.__qualname__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                inputs: dict[str, Any] = {}
                if capture_inputs:
                    sig = inspect.signature(fn)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    inputs = {k: _safe_serialize(v) for k, v in bound.arguments.items()}
                async with aspan(span_name, inputs=inputs, tags=tags) as s:
                    result = await fn(*args, **kwargs)
                    if capture_output:
                        s.set_output({"return": _safe_serialize(result)})
                    return result

            return async_wrapper  # type: ignore[return-value]
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                inputs: dict[str, Any] = {}
                if capture_inputs:
                    sig = inspect.signature(fn)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    inputs = {k: _safe_serialize(v) for k, v in bound.arguments.items()}
                with span(span_name, inputs=inputs, tags=tags) as s:
                    result = fn(*args, **kwargs)
                    if capture_output:
                        s.set_output({"return": _safe_serialize(result)})
                    return result

            return sync_wrapper  # type: ignore[return-value]

    if func is not None:
        return decorator(func)
    return decorator  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_serialize(value: Any, max_len: int = 4096) -> Any:
    """Convert any value to a JSON-safe representation, safely truncating large ones."""
    if isinstance(value, (str, int, float, bool, type(None))):
        if isinstance(value, str) and len(value) > max_len:
            return value[:max_len] + f"... [{len(value) - max_len} chars truncated]"
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_serialize(v, max_len) for v in value[:50]]
    if isinstance(value, dict):
        return {k: _safe_serialize(v, max_len) for k, v in list(value.items())[:50]}
    # For anything else (dataclasses, Pydantic models, etc.)
    try:
        import dataclasses

        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return dataclasses.asdict(value)
    except Exception:  # noqa: S110
        pass
    try:
        if hasattr(value, "model_dump"):  # Pydantic v2
            return value.model_dump()
        if hasattr(value, "dict"):  # Pydantic v1
            return value.dict()
    except Exception:  # noqa: S110
        pass
    return repr(value)[:max_len]
