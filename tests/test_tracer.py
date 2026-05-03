"""
tests/test_tracer.py
~~~~~~~~~~~~~~~~~~~~
Unit tests for the core tracing system.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import trazo as tz
from trazo.collector import get_collector
from trazo.models import SpanStatus
from trazo.storage import StorageEngine
from trazo.tracer import get_current_run, get_current_span


@pytest.fixture(autouse=True)
def fresh_storage(tmp_path: Path):
    """Each test gets its own clean SQLite database."""
    db = tmp_path / "test_traces.db"
    storage = StorageEngine(db_path=db)
    collector = get_collector()
    collector.configure(storage)
    yield storage
    collector.flush(timeout=2.0)


# ---------------------------------------------------------------------------
# @tz.trace decorator
# ---------------------------------------------------------------------------


def test_trace_decorator_sync():
    @tz.trace
    def add(a: int, b: int) -> int:
        return a + b

    with tz.run("test_run") as r:
        result = add(2, 3)

    assert result == 5
    get_collector().flush()
    storage = get_collector().storage
    spans = storage.get_spans_for_run(r.run_id)
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "test_trace_decorator_sync.<locals>.add"
    assert s.inputs == {"a": 2, "b": 3}
    assert s.outputs == {"return": 5}
    assert s.status == SpanStatus.OK


def test_trace_decorator_async():
    @tz.trace
    async def async_add(x: int) -> int:
        return x * 2

    async def run_it():
        with tz.run("async_test") as r:
            result = await async_add(21)
        return r.run_id, result

    run_id, result = asyncio.run(run_it())
    assert result == 42
    get_collector().flush()
    spans = get_collector().storage.get_spans_for_run(run_id)
    assert any(s.name == "test_trace_decorator_async.<locals>.async_add" for s in spans)


def test_trace_captures_exception():
    @tz.trace
    def fail_func() -> None:
        raise ValueError("intentional error")

    with tz.run("error_test") as r:
        with pytest.raises(ValueError):
            fail_func()

    get_collector().flush()
    spans = get_collector().storage.get_spans_for_run(r.run_id)
    assert len(spans) == 1
    s = spans[0]
    assert s.status == SpanStatus.ERROR
    assert "intentional error" in (s.error or "")


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------


def test_span_context_manager():
    with tz.run("ctx_test") as r:
        with tz.span("step_one", inputs={"key": "val"}) as s:
            s.set_output({"result": 42})
            s.set_model("gpt-4o")
            s.set_tokens(100, 50)
            s.set_cost(0.00123)
            s.tag("env", "test")

    get_collector().flush()
    spans = get_collector().storage.get_spans_for_run(r.run_id)
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "step_one"
    assert s.outputs == {"result": 42}
    assert s.model == "gpt-4o"
    assert s.tokens_in == 100
    assert s.tokens_out == 50
    assert abs(s.cost_usd - 0.00123) < 1e-9
    assert s.tags.get("env") == "test"


def test_nested_spans_parent_child():
    with tz.run("nested") as r:
        with tz.span("parent"):
            with tz.span("child"):
                pass

    get_collector().flush()
    spans = {s.name: s for s in get_collector().storage.get_spans_for_run(r.run_id)}
    assert "parent" in spans
    assert "child" in spans
    assert spans["child"].parent_span_id == spans["parent"].span_id


def test_context_vars_reset_after_span():
    """ContextVars must be properly reset after each span to avoid leakage."""
    with tz.run("ctx_reset"):
        with tz.span("a"):
            span_inside = get_current_span()
            assert span_inside is not None
            assert span_inside.name == "a"
        span_after = get_current_span()
        assert span_after is None


# ---------------------------------------------------------------------------
# Run context manager
# ---------------------------------------------------------------------------


def test_run_creates_and_finalizes():
    with tz.run("my_run", metadata={"version": "v1"}) as r:
        run_id = r.run_id
        assert get_current_run() is not None

    assert get_current_run() is None
    get_collector().flush()

    stored_run = get_collector().storage.get_run(run_id)
    assert stored_run is not None
    assert stored_run.name == "my_run"
    assert stored_run.status == SpanStatus.OK
    assert stored_run.metadata.get("version") == "v1"


def test_run_status_error_on_exception():
    try:
        with tz.run("failing_run") as r:
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    get_collector().flush()
    stored = get_collector().storage.get_run(r.run_id)
    assert stored.status == SpanStatus.ERROR


# ---------------------------------------------------------------------------
# Async span
# ---------------------------------------------------------------------------


def test_aspan_context_manager():
    async def inner():
        with tz.run("async_run") as r:
            async with tz.aspan("async_step", inputs={"x": 1}) as s:
                await asyncio.sleep(0.01)
                s.set_output({"done": True})
        return r.run_id

    run_id = asyncio.run(inner())
    get_collector().flush()
    spans = get_collector().storage.get_spans_for_run(run_id)
    assert any(s.name == "async_step" for s in spans)


# ---------------------------------------------------------------------------
# Custom name and tags on decorator
# ---------------------------------------------------------------------------


def test_trace_custom_name_and_tags():
    @tz.trace(name="custom.name", tags={"tier": "llm", "env": "test"})
    def fn() -> str:
        return "hello"

    with tz.run("tags_test") as r:
        fn()

    get_collector().flush()
    spans = get_collector().storage.get_spans_for_run(r.run_id)
    s = spans[0]
    assert s.name == "custom.name"
    assert s.tags.get("tier") == "llm"
