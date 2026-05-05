"""
tests/test_storage.py
~~~~~~~~~~~~~~~~~~~~~
Unit tests for the SQLite storage engine.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from trazo.models import Run, Span, SpanStatus
from trazo.storage import StorageEngine


@pytest.fixture
def storage(tmp_path: Path) -> StorageEngine:
    return StorageEngine(db_path=tmp_path / "test.db")


def make_run(**kwargs) -> Run:
    t = time.time()
    defaults = {"name": "test_run", "started_at": t, "ended_at": t + 1.0, "status": SpanStatus.OK}
    defaults.update(kwargs)
    return Run(**defaults)


def make_span(run_id: str, **kwargs) -> Span:
    t = time.time()
    defaults = {
        "run_id": run_id,
        "name": "test_span",
        "started_at": t,
        "ended_at": t + 0.5,
        "status": SpanStatus.OK,
    }
    defaults.update(kwargs)
    return Span(**defaults)


# ---------------------------------------------------------------------------
# Run CRUD
# ---------------------------------------------------------------------------


def test_upsert_and_get_run(storage):
    r = make_run(name="my_run", metadata={"key": "val"})
    storage.upsert_run(r)
    fetched = storage.get_run(r.run_id)
    assert fetched is not None
    assert fetched.name == "my_run"
    assert fetched.metadata == {"key": "val"}


def test_upsert_run_updates_on_conflict(storage):
    r = make_run(name="initial")
    storage.upsert_run(r)
    r.name = "updated"
    r.status = SpanStatus.ERROR
    storage.upsert_run(r)
    fetched = storage.get_run(r.run_id)
    assert fetched.status == SpanStatus.ERROR


def test_list_runs_order(storage):
    for i in range(5):
        r = make_run(name=f"run_{i}")
        r.started_at = time.time() + i
        storage.upsert_run(r)

    runs = storage.list_runs(limit=3)
    assert len(runs) == 3
    # Should be newest first
    assert runs[0].started_at >= runs[1].started_at


def test_delete_run_cascades(storage):
    r = make_run()
    storage.upsert_run(r)
    s = make_span(r.run_id)
    storage.upsert_span(s)
    storage.delete_run(r.run_id)
    assert storage.get_run(r.run_id) is None
    assert storage.get_spans_for_run(r.run_id) == []


# ---------------------------------------------------------------------------
# Span CRUD
# ---------------------------------------------------------------------------


def test_upsert_and_get_span(storage):
    r = make_run()
    storage.upsert_run(r)
    s = make_span(
        r.run_id,
        name="parse",
        inputs={"x": 1},
        outputs={"y": 2},
        model="gpt-4o",
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.00123,
    )
    storage.upsert_span(s)
    fetched = storage.get_span(s.span_id)
    assert fetched.name == "parse"
    assert fetched.inputs == {"x": 1}
    assert fetched.outputs == {"y": 2}
    assert fetched.model == "gpt-4o"
    assert fetched.tokens_in == 100
    assert abs(fetched.cost_usd - 0.00123) < 1e-9


def test_get_spans_for_run_ordered(storage):
    r = make_run()
    storage.upsert_run(r)
    for i in range(4):
        s = make_span(r.run_id, name=f"span_{i}")
        s.started_at = time.time() + i * 0.1
        storage.upsert_span(s)

    spans = storage.get_spans_for_run(r.run_id)
    assert len(spans) == 4
    names = [s.name for s in spans]
    assert names == sorted(names)  # ordered by started_at ASC


def test_span_with_error(storage):
    r = make_run()
    storage.upsert_run(r)
    s = make_span(r.run_id, status=SpanStatus.ERROR, error="something went wrong")
    storage.upsert_span(s)
    fetched = storage.get_span(s.span_id)
    assert fetched.status == SpanStatus.ERROR
    assert fetched.error == "something went wrong"


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def test_upsert_and_get_embedding(storage):
    r = make_run()
    storage.upsert_run(r)
    s = make_span(r.run_id)
    storage.upsert_span(s)
    vector = [0.1, 0.2, 0.3, 0.4]
    storage.upsert_embedding(s.span_id, vector)
    fetched = storage.get_embedding(s.span_id)
    assert fetched == pytest.approx(vector)


def test_embeddings_for_run(storage):
    r = make_run()
    storage.upsert_run(r)
    for i in range(3):
        s = make_span(r.run_id, name=f"s_{i}")
        storage.upsert_span(s)
        storage.upsert_embedding(s.span_id, [float(i)] * 4)
    embs = storage.get_embeddings_for_run(r.run_id)
    assert len(embs) == 3


# ---------------------------------------------------------------------------
# Aggregate refresh
# ---------------------------------------------------------------------------


def test_refresh_run_aggregates(storage):
    r = make_run()
    storage.upsert_run(r)
    for _i in range(3):
        s = make_span(r.run_id, tokens_in=100, tokens_out=50, cost_usd=0.001)
        storage.upsert_span(s)
    storage.refresh_run_aggregates(r.run_id)
    updated = storage.get_run(r.run_id)
    assert updated.span_count == 3
    assert updated.total_tokens_in == 300
    assert updated.total_tokens_out == 150
    assert abs(updated.total_cost_usd - 0.003) < 1e-9
