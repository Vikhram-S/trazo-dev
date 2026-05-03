"""
Trazo.models
~~~~~~~~~~~~~~~~
Core data models for Trazo's execution tracing system.
All models are Pydantic v2 compatible with full type safety.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SpanStatus(str, Enum):
    """Lifecycle status of an execution span."""
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    ERROR = "error"


class DiffKind(str, Enum):
    """Category of difference detected in a semantic diff."""
    IDENTICAL = "identical"
    SIMILAR = "similar"
    DIVERGED = "diverged"
    ADDED = "added"
    REMOVED = "removed"


# ---------------------------------------------------------------------------
# Span — the atomic unit of a traced execution
# ---------------------------------------------------------------------------


class Span(BaseModel):
    """
    A Span represents a single instrumented function call within a pipeline run.
    Spans form a tree via parent_span_id, allowing DAG reconstruction.
    """
    span_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    name: str
    parent_span_id: str | None = None
    started_at: float  # Unix timestamp (seconds, fractional)
    ended_at: float | None = None
    status: SpanStatus = SpanStatus.PENDING

    # Serialized inputs/outputs (arbitrary JSON-compatible dicts)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] | None = None
    error: str | None = None

    # LLM-specific metadata
    model: str | None = None
    provider: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None

    # Tags allow grouping and filtering
    tags: dict[str, str] = Field(default_factory=dict)

    # Semantic embedding vector for diff engine (stored separately)
    # Not included in standard serialization to keep payloads small
    embedding: list[float] | None = Field(default=None, exclude=True)

    @property
    def duration_ms(self) -> float | None:
        """Wall-clock duration of this span in milliseconds."""
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at) * 1000
        return None

    @property
    def is_llm_call(self) -> bool:
        """True if this span represents an LLM inference call."""
        return self.model is not None

    def output_text(self) -> str | None:
        """Extract a plain-text representation of the span's output."""
        if not self.outputs:
            return None
        # Common LLM response shapes
        for key in ("content", "text", "message", "result", "output"):
            if key in self.outputs:
                val = self.outputs[key]
                if isinstance(val, str):
                    return val
                if isinstance(val, dict):
                    return str(val)
        return str(self.outputs)


# ---------------------------------------------------------------------------
# Run — a complete pipeline execution
# ---------------------------------------------------------------------------


class Run(BaseModel):
    """
    A Run represents one top-level execution of a traced pipeline.
    Multiple Spans belong to a single Run.
    """
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "unnamed"
    started_at: float
    ended_at: float | None = None
    status: SpanStatus = SpanStatus.RUNNING

    # Aggregate metrics (computed from child spans)
    total_cost_usd: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    span_count: int = 0

    # Free-form metadata (e.g., git commit, env, user, experiment name)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at) * 1000
        return None

    @property
    def total_tokens(self) -> int:
        return self.total_tokens_in + self.total_tokens_out


# ---------------------------------------------------------------------------
# Diff — semantic comparison between two spans or runs
# ---------------------------------------------------------------------------


class SpanDiff(BaseModel):
    """Semantic difference between two corresponding spans across runs."""
    span_name: str
    kind: DiffKind
    similarity_score: float  # 0.0 (totally different) to 1.0 (identical)
    run_a_span_id: str | None = None
    run_b_span_id: str | None = None
    # Textual representations of inputs/outputs for display
    run_a_output: str | None = None
    run_b_output: str | None = None
    cost_delta_usd: float | None = None
    latency_delta_ms: float | None = None
    token_delta: int | None = None

    @field_validator("similarity_score")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class RunDiff(BaseModel):
    """Complete semantic diff between two pipeline runs."""
    run_a_id: str
    run_b_id: str
    run_a_name: str
    run_b_name: str
    generated_at: float
    span_diffs: list[SpanDiff] = Field(default_factory=list)

    # Aggregate deltas
    cost_delta_usd: float = 0.0
    latency_delta_ms: float = 0.0
    token_delta: int = 0

    @property
    def changed_spans(self) -> list[SpanDiff]:
        return [d for d in self.span_diffs if d.kind != DiffKind.IDENTICAL]

    @property
    def overall_similarity(self) -> float:
        if not self.span_diffs:
            return 1.0
        return sum(d.similarity_score for d in self.span_diffs) / len(self.span_diffs)


# ---------------------------------------------------------------------------
# ReplayRequest — inputs for time-travel re-execution
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    """Request to re-execute a specific span using its original inputs."""
    source_run_id: str
    source_span_id: str
    override_inputs: dict[str, Any] | None = None  # Optional input overrides
    dry_run: bool = False  # If True, return inputs without executing
