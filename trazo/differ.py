"""
Trazo.differ
~~~~~~~~~~~~~~~~
Semantic diff engine for comparing two pipeline runs.

Strategy:
1. Pair spans across runs by name (best-effort matching)
2. Compute cosine similarity on text fingerprints of inputs/outputs
3. Compute structural diffs on JSON inputs
4. Report cost/latency/token deltas

No ML model required — uses lightweight TF-IDF-style character n-gram hashing
by default. If sentence-transformers is available, uses real semantic embeddings.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter, defaultdict
from typing import cast

from .models import DiffKind, Run, RunDiff, Span, SpanDiff
from .storage import StorageEngine

# Similarity thresholds
_IDENTICAL_THRESHOLD = 0.97
_SIMILAR_THRESHOLD = 0.65


# ---------------------------------------------------------------------------
# Vectorization
# ---------------------------------------------------------------------------


def _char_ngrams(text: str, n: int = 3) -> Counter[str]:
    """Build a character n-gram bag-of-words counter."""
    text = text.lower().strip()
    if len(text) < n:
        return Counter({text: 1})
    return Counter(text[i : i + n] for i in range(len(text) - n + 1))


def _tfidf_vector(text: str) -> dict[str, float]:
    """
    Simple TF vector from character 3-grams.
    Normalized to unit length for cosine similarity.
    """
    counts = _char_ngrams(text)
    if not counts:
        return {}
    total = sum(counts.values())
    vec = {gram: count / total for gram, count in counts.items()}
    # L2-normalize
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm == 0:
        return vec
    return {k: v / norm for k, v in vec.items()}


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF vectors."""
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0.0) * v for k, v in b.items())
    return max(0.0, min(1.0, dot))


def _span_fingerprint(span: Span) -> str:
    """Create a canonical text fingerprint of a span's I/O for vectorization."""
    parts: list[str] = []
    if span.inputs:
        parts.append(json.dumps(span.inputs, sort_keys=True, default=str))
    if span.outputs:
        parts.append(json.dumps(span.outputs, sort_keys=True, default=str))
    return " ".join(parts)


def _compute_similarity(span_a: Span, span_b: Span) -> float:
    """Compute semantic similarity between two spans."""
    # Try to use stored embeddings first (if sentence-transformers was used)
    if span_a.embedding and span_b.embedding:
        return _cosine_similarity_dense(span_a.embedding, span_b.embedding)

    fp_a = _span_fingerprint(span_a)
    fp_b = _span_fingerprint(span_b)

    if not fp_a and not fp_b:
        return 1.0
    if not fp_a or not fp_b:
        return 0.0
    if fp_a == fp_b:
        return 1.0

    vec_a = _tfidf_vector(fp_a)
    vec_b = _tfidf_vector(fp_b)
    return _cosine_similarity(vec_a, vec_b)


def _cosine_similarity_dense(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two dense vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


# ---------------------------------------------------------------------------
# Span matching
# ---------------------------------------------------------------------------


def _match_spans(
    spans_a: list[Span],
    spans_b: list[Span],
) -> list[tuple[Span | None, Span | None]]:
    """
    Match spans from run A to run B by name.
    Uses a greedy approach: first exact name match, then order-based fallback.
    Returns list of (span_a, span_b) pairs where None means added/removed.
    """
    # Group by name
    by_name_a: dict[str, list[Span]] = defaultdict(list)
    by_name_b: dict[str, list[Span]] = defaultdict(list)
    for s in spans_a:
        by_name_a[s.name].append(s)
    for s in spans_b:
        by_name_b[s.name].append(s)

    pairs: list[tuple[Span | None, Span | None]] = []
    all_names = sorted(
        set(by_name_a.keys()) | set(by_name_b.keys()),
        key=lambda n: (
            min((s.started_at for s in by_name_a.get(n, [])), default=float("inf")),
            min((s.started_at for s in by_name_b.get(n, [])), default=float("inf")),
        ),
    )

    for name in all_names:
        group_a = by_name_a.get(name, [])
        group_b = by_name_b.get(name, [])
        max_len = max(len(group_a), len(group_b))
        for i in range(max_len):
            span_a = group_a[i] if i < len(group_a) else None
            span_b = group_b[i] if i < len(group_b) else None
            pairs.append((span_a, span_b))

    return pairs


# ---------------------------------------------------------------------------
# Main diff function
# ---------------------------------------------------------------------------


def diff_runs(
    run_a: Run,
    run_b: Run,
    storage: StorageEngine,
) -> RunDiff:
    """
    Compute a full semantic diff between two runs.

    Args:
        run_a: The "baseline" run (typically the older one)
        run_b: The "new" run to compare against the baseline
        storage: Storage engine to load spans from

    Returns:
        A RunDiff object with per-span diffs and aggregate deltas
    """
    spans_a = storage.get_spans_for_run(run_a.run_id)
    spans_b = storage.get_spans_for_run(run_b.run_id)

    pairs = _match_spans(spans_a, spans_b)
    span_diffs: list[SpanDiff] = []

    for span_a, span_b in pairs:
        if span_a is None and span_b is not None:
            diff = SpanDiff(
                span_name=span_b.name,
                kind=DiffKind.ADDED,
                similarity_score=0.0,
                run_b_span_id=span_b.span_id,
                run_b_output=span_b.output_text(),
            )
        elif span_a is not None and span_b is None:
            diff = SpanDiff(
                span_name=span_a.name,
                kind=DiffKind.REMOVED,
                similarity_score=0.0,
                run_a_span_id=span_a.span_id,
                run_a_output=span_a.output_text(),
            )
        else:
            assert span_a is not None
            assert span_b is not None
            sim = _compute_similarity(span_a, span_b)

            if sim >= _IDENTICAL_THRESHOLD:
                kind = DiffKind.IDENTICAL
            elif sim >= _SIMILAR_THRESHOLD:
                kind = DiffKind.SIMILAR
            else:
                kind = DiffKind.DIVERGED

            cost_delta = None
            if span_a.cost_usd is not None and span_b.cost_usd is not None:
                cost_delta = span_b.cost_usd - span_a.cost_usd

            latency_delta = None
            if span_a.duration_ms is not None and span_b.duration_ms is not None:
                latency_delta = span_b.duration_ms - span_a.duration_ms

            token_delta = None
            tok_a = (span_a.tokens_in or 0) + (span_a.tokens_out or 0)
            tok_b = (span_b.tokens_in or 0) + (span_b.tokens_out or 0)
            if tok_a or tok_b:
                token_delta = tok_b - tok_a

            diff = SpanDiff(
                span_name=span_a.name,
                kind=kind,
                similarity_score=sim,
                run_a_span_id=span_a.span_id,
                run_b_span_id=span_b.span_id,
                run_a_output=span_a.output_text(),
                run_b_output=span_b.output_text(),
                cost_delta_usd=cost_delta,
                latency_delta_ms=latency_delta,
                token_delta=token_delta,
            )

        span_diffs.append(diff)

    # Aggregate deltas
    cost_delta = (run_b.total_cost_usd or 0.0) - (run_a.total_cost_usd or 0.0)
    latency_delta = (run_b.duration_ms or 0.0) - (run_a.duration_ms or 0.0)
    token_delta = run_b.total_tokens - run_a.total_tokens

    return RunDiff(
        run_a_id=run_a.run_id,
        run_b_id=run_b.run_id,
        run_a_name=run_a.name,
        run_b_name=run_b.name,
        generated_at=time.time(),
        span_diffs=span_diffs,
        cost_delta_usd=cost_delta,
        latency_delta_ms=latency_delta,
        token_delta=token_delta,
    )


# ---------------------------------------------------------------------------
# Optional: sentence-transformers integration
# ---------------------------------------------------------------------------


def embed_span(span: Span) -> list[float] | None:
    """
    Generate a semantic embedding for a span using sentence-transformers.
    Returns None if sentence-transformers is not installed.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None

    text = _span_fingerprint(span)
    if not text:
        return None

    # Cache model to avoid reloading
    if not hasattr(embed_span, "_model"):
        embed_span._model = SentenceTransformer("all-MiniLM-L6-v2")  # type: ignore[attr-defined]

    embedding = embed_span._model.encode(text, normalize_embeddings=True)  # type: ignore[attr-defined]
    return cast(list[float], embedding.tolist())
