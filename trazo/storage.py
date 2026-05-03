"""
Trazo.storage
~~~~~~~~~~~~~~~~~
SQLite-backed storage engine for runs and spans.
Uses only the Python standard library — zero external dependencies for storage.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .models import Run, Span, SpanStatus

# Default storage location: ~/.trazo/traces.db
_DEFAULT_DB_PATH = Path.home() / ".trazo" / "traces.db"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    started_at      REAL NOT NULL,
    ended_at        REAL,
    status          TEXT NOT NULL DEFAULT 'running',
    total_cost_usd  REAL NOT NULL DEFAULT 0.0,
    total_tokens_in INTEGER NOT NULL DEFAULT 0,
    total_tokens_out INTEGER NOT NULL DEFAULT 0,
    span_count      INTEGER NOT NULL DEFAULT 0,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS spans (
    span_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    parent_span_id  TEXT,
    started_at      REAL NOT NULL,
    ended_at        REAL,
    status          TEXT NOT NULL DEFAULT 'pending',
    inputs          TEXT NOT NULL DEFAULT '{}',
    outputs         TEXT,
    error           TEXT,
    model           TEXT,
    provider        TEXT,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_usd        REAL,
    tags            TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS embeddings (
    span_id     TEXT PRIMARY KEY REFERENCES spans(span_id) ON DELETE CASCADE,
    vector      TEXT NOT NULL  -- JSON-encoded list[float]
);

CREATE INDEX IF NOT EXISTS idx_spans_run_id ON spans(run_id);
CREATE INDEX IF NOT EXISTS idx_spans_name   ON spans(name);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
"""


# ---------------------------------------------------------------------------
# StorageEngine
# ---------------------------------------------------------------------------


class StorageEngine:
    """
    Thread-safe SQLite storage engine.
    Uses a per-thread connection pool to avoid cross-thread connection issues.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # Apply schema on first connection
        with self._connection() as conn:
            conn.executescript(_DDL)
            conn.commit()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Return a per-thread SQLite connection, creating one if needed."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_conn()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Run operations
    # ------------------------------------------------------------------

    def upsert_run(self, run: Run) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO runs
                    (run_id, name, started_at, ended_at, status,
                     total_cost_usd, total_tokens_in, total_tokens_out,
                     span_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    ended_at        = excluded.ended_at,
                    status          = excluded.status,
                    total_cost_usd  = excluded.total_cost_usd,
                    total_tokens_in  = excluded.total_tokens_in,
                    total_tokens_out = excluded.total_tokens_out,
                    span_count      = excluded.span_count,
                    metadata        = excluded.metadata
                """,
                (
                    run.run_id,
                    run.name,
                    run.started_at,
                    run.ended_at,
                    run.status.value,
                    run.total_cost_usd,
                    run.total_tokens_in,
                    run.total_tokens_out,
                    run.span_count,
                    json.dumps(run.metadata),
                ),
            )
            conn.commit()

    def get_run(self, run_id: str) -> Run | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(self, limit: int = 50) -> list[Run]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_run(r) for r in rows]

    def delete_run(self, run_id: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            conn.commit()

    # ------------------------------------------------------------------
    # Span operations
    # ------------------------------------------------------------------

    def upsert_span(self, span: Span) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO spans
                    (span_id, run_id, name, parent_span_id,
                     started_at, ended_at, status,
                     inputs, outputs, error,
                     model, provider, tokens_in, tokens_out, cost_usd, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(span_id) DO UPDATE SET
                    ended_at       = excluded.ended_at,
                    status         = excluded.status,
                    outputs        = excluded.outputs,
                    error          = excluded.error,
                    tokens_in      = excluded.tokens_in,
                    tokens_out     = excluded.tokens_out,
                    cost_usd       = excluded.cost_usd
                """,
                (
                    span.span_id,
                    span.run_id,
                    span.name,
                    span.parent_span_id,
                    span.started_at,
                    span.ended_at,
                    span.status.value,
                    json.dumps(span.inputs),
                    json.dumps(span.outputs) if span.outputs is not None else None,
                    span.error,
                    span.model,
                    span.provider,
                    span.tokens_in,
                    span.tokens_out,
                    span.cost_usd,
                    json.dumps(span.tags),
                ),
            )
            conn.commit()

        # Persist embedding separately if present
        if span.embedding is not None:
            self.upsert_embedding(span.span_id, span.embedding)

    def get_span(self, span_id: str) -> Span | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM spans WHERE span_id = ?", (span_id,)).fetchone()
        return _row_to_span(row) if row else None

    def get_spans_for_run(self, run_id: str) -> list[Span]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at ASC",
                (run_id,),
            ).fetchall()
        return [_row_to_span(r) for r in rows]

    def get_spans_by_name(self, name: str, limit: int = 100) -> list[Span]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM spans WHERE name = ? ORDER BY started_at DESC LIMIT ?",
                (name, limit),
            ).fetchall()
        return [_row_to_span(r) for r in rows]

    # ------------------------------------------------------------------
    # Embedding operations
    # ------------------------------------------------------------------

    def upsert_embedding(self, span_id: str, vector: list[float]) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO embeddings (span_id, vector)
                VALUES (?, ?)
                ON CONFLICT(span_id) DO UPDATE SET vector = excluded.vector
                """,
                (span_id, json.dumps(vector)),
            )
            conn.commit()

    def get_embedding(self, span_id: str) -> list[float] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT vector FROM embeddings WHERE span_id = ?", (span_id,)
            ).fetchone()
        return json.loads(row["vector"]) if row else None

    def get_embeddings_for_run(self, run_id: str) -> dict[str, list[float]]:
        """Returns {span_id: vector} for all embedded spans in a run."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT e.span_id, e.vector
                FROM embeddings e
                JOIN spans s ON e.span_id = s.span_id
                WHERE s.run_id = ?
                """,
                (run_id,),
            ).fetchall()
        return {r["span_id"]: json.loads(r["vector"]) for r in rows}

    # ------------------------------------------------------------------
    # Aggregate updates (called when runs finish)
    # ------------------------------------------------------------------

    def refresh_run_aggregates(self, run_id: str) -> None:
        """Recompute and persist aggregate metrics for a run from its spans."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)                        AS span_count,
                    COALESCE(SUM(cost_usd), 0.0)   AS total_cost_usd,
                    COALESCE(SUM(tokens_in), 0)    AS total_tokens_in,
                    COALESCE(SUM(tokens_out), 0)   AS total_tokens_out
                FROM spans
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            conn.execute(
                """
                UPDATE runs
                SET span_count      = ?,
                    total_cost_usd  = ?,
                    total_tokens_in  = ?,
                    total_tokens_out = ?
                WHERE run_id = ?
                """,
                (
                    row["span_count"],
                    row["total_cost_usd"],
                    row["total_tokens_in"],
                    row["total_tokens_out"],
                    run_id,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def db_path(self) -> Path:
        return self._db_path


# ---------------------------------------------------------------------------
# Row → Model converters
# ---------------------------------------------------------------------------


def _row_to_run(row: sqlite3.Row) -> Run:
    return Run(
        run_id=row["run_id"],
        name=row["name"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        status=SpanStatus(row["status"]),
        total_cost_usd=row["total_cost_usd"],
        total_tokens_in=row["total_tokens_in"],
        total_tokens_out=row["total_tokens_out"],
        span_count=row["span_count"],
        metadata=json.loads(row["metadata"]),
    )


def _row_to_span(row: sqlite3.Row) -> Span:
    return Span(
        span_id=row["span_id"],
        run_id=row["run_id"],
        name=row["name"],
        parent_span_id=row["parent_span_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        status=SpanStatus(row["status"]),
        inputs=json.loads(row["inputs"]),
        outputs=json.loads(row["outputs"]) if row["outputs"] else None,
        error=row["error"],
        model=row["model"],
        provider=row["provider"],
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        cost_usd=row["cost_usd"],
        tags=json.loads(row["tags"]),
    )
