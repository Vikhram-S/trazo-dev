"""
tests/test_differ.py
~~~~~~~~~~~~~~~~~~~~
Unit tests for the semantic diff engine.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from trazo.differ import (
    _compute_similarity,
    _cosine_similarity,
    _tfidf_vector,
    diff_runs,
)
from trazo.models import DiffKind, Run, Span, SpanStatus
from trazo.storage import StorageEngine


def make_span(
    run_id: str,
    name: str,
    inputs: dict | None = None,
    outputs: dict | None = None,
    model: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float | None = None,
    started_offset: float = 0.0,
    parent_span_id: str | None = None,
) -> Span:
    t0 = time.time() + started_offset
    return Span(
        run_id=run_id,
        name=name,
        parent_span_id=parent_span_id,
        started_at=t0,
        ended_at=t0 + 0.1,
        status=SpanStatus.OK,
        inputs=inputs or {},
        outputs=outputs or {},
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )


def make_run(name: str, cost: float = 0.0, tokens_in: int = 0, tokens_out: int = 0) -> Run:
    t = time.time()
    return Run(
        name=name,
        started_at=t,
        ended_at=t + 1.0,
        status=SpanStatus.OK,
        total_cost_usd=cost,
        total_tokens_in=tokens_in,
        total_tokens_out=tokens_out,
        span_count=2,
    )


@pytest.fixture
def storage(tmp_path: Path):
    return StorageEngine(db_path=tmp_path / "diff_test.db")


# ---------------------------------------------------------------------------
# Vectorization
# ---------------------------------------------------------------------------


def test_tfidf_vector_unit_length():
    import math
    vec = _tfidf_vector("hello world this is a test")
    norm = math.sqrt(sum(v * v for v in vec.values()))
    assert abs(norm - 1.0) < 1e-6


def test_cosine_similarity_identical():
    vec = _tfidf_vector("the quick brown fox")
    assert _cosine_similarity(vec, vec) == pytest.approx(1.0, abs=1e-6)


def test_cosine_similarity_orthogonal():
    # Two vectors with no shared n-grams
    vec_a = {"abc": 1.0}
    vec_b = {"xyz": 1.0}
    assert _cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)


def test_compute_similarity_identical_text():
    text = "The model generated this exact response"
    s1 = make_span("r1", "step", outputs={"content": text})
    s2 = make_span("r2", "step", outputs={"content": text})
    sim = _compute_similarity(s1, s2)
    assert sim > 0.97


def test_compute_similarity_different_text():
    s1 = make_span("r1", "step", outputs={"content": "Python is great for data science"})
    s2 = make_span("r2", "step", outputs={"content": "Rust enables memory-safe systems programming"})
    sim = _compute_similarity(s1, s2)
    assert sim < 0.7


# ---------------------------------------------------------------------------
# diff_runs
# ---------------------------------------------------------------------------


def test_diff_identical_runs(storage):
    run_a = make_run("run_a", cost=0.001, tokens_in=100, tokens_out=50)
    run_b = make_run("run_b", cost=0.001, tokens_in=100, tokens_out=50)
    storage.upsert_run(run_a)
    storage.upsert_run(run_b)

    for run in [run_a, run_b]:
        storage.upsert_span(make_span(run.run_id, "step_one", outputs={"result": "same output"}))
        storage.upsert_span(make_span(run.run_id, "step_two", outputs={"data": "identical"}))

    result = diff_runs(run_a, run_b, storage)
    assert result.overall_similarity > 0.97
    assert all(d.kind == DiffKind.IDENTICAL for d in result.span_diffs)


def test_diff_diverged_runs(storage):
    run_a = make_run("run_a", cost=0.001, tokens_in=100, tokens_out=50)
    run_b = make_run("run_b", cost=0.003, tokens_in=200, tokens_out=150)
    storage.upsert_run(run_a)
    storage.upsert_run(run_b)

    storage.upsert_span(make_span(run_a.run_id, "step_one",
        outputs={"content": "Python excels at rapid prototyping"}))
    storage.upsert_span(make_span(run_b.run_id, "step_one",
        outputs={"content": "Quantum entanglement allows non-local correlations in physics"}))

    result = diff_runs(run_a, run_b, storage)
    assert result.overall_similarity < 0.7
    assert any(d.kind == DiffKind.DIVERGED for d in result.span_diffs)


def test_diff_added_span(storage):
    run_a = make_run("run_a")
    run_b = make_run("run_b")
    storage.upsert_run(run_a)
    storage.upsert_run(run_b)

    storage.upsert_span(make_span(run_a.run_id, "common_step"))
    storage.upsert_span(make_span(run_b.run_id, "common_step"))
    storage.upsert_span(make_span(run_b.run_id, "new_step"))  # only in B

    result = diff_runs(run_a, run_b, storage)
    kinds = {d.span_name: d.kind for d in result.span_diffs}
    assert kinds.get("new_step") == DiffKind.ADDED


def test_diff_removed_span(storage):
    run_a = make_run("run_a")
    run_b = make_run("run_b")
    storage.upsert_run(run_a)
    storage.upsert_run(run_b)

    storage.upsert_span(make_span(run_a.run_id, "common_step"))
    storage.upsert_span(make_span(run_a.run_id, "old_step"))  # only in A
    storage.upsert_span(make_span(run_b.run_id, "common_step"))

    result = diff_runs(run_a, run_b, storage)
    kinds = {d.span_name: d.kind for d in result.span_diffs}
    assert kinds.get("old_step") == DiffKind.REMOVED


def test_diff_cost_and_token_deltas(storage):
    run_a = make_run("run_a", cost=0.001, tokens_in=100, tokens_out=50)
    run_b = make_run("run_b", cost=0.003, tokens_in=200, tokens_out=100)
    storage.upsert_run(run_a)
    storage.upsert_run(run_b)
    storage.upsert_span(make_span(run_a.run_id, "s1"))
    storage.upsert_span(make_span(run_b.run_id, "s1"))

    result = diff_runs(run_a, run_b, storage)
    assert result.cost_delta_usd == pytest.approx(0.002, abs=1e-9)
    assert result.token_delta == 150
