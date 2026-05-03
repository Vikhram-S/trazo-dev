"""
Trazo.integrations.openai_patch
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Auto-instrumentation for the OpenAI Python SDK (v1.x+).

Patches openai.chat.completions.create (and acreate) to automatically
create spans with token counts, cost estimation, and model metadata.

Usage:
    import trazo as tz
    tz.instrument_openai()  # Call once at startup
"""

from __future__ import annotations

import time
from typing import Any

from ..collector import get_collector
from ..models import Span, SpanStatus
from ..tracer import _current_run, _current_span

# ---------------------------------------------------------------------------
# OpenAI pricing (USD per 1K tokens) — updated for common models
# Extend this dict as new models are released
# ---------------------------------------------------------------------------
_OPENAI_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1k, output_per_1k)
    "gpt-4o": (0.0025, 0.010),
    "gpt-4o-mini": (0.000150, 0.000600),
    "gpt-4-turbo": (0.010, 0.030),
    "gpt-4": (0.030, 0.060),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "o1": (0.015, 0.060),
    "o1-mini": (0.003, 0.012),
    "o3-mini": (0.001, 0.004),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float | None:
    for key, (in_rate, out_rate) in _OPENAI_PRICING.items():
        if model.startswith(key):
            return (tokens_in / 1000 * in_rate) + (tokens_out / 1000 * out_rate)
    return None


def _extract_text_from_response(response: Any) -> str | None:
    """Extract plain text from an OpenAI chat completion response."""
    try:
        return response.choices[0].message.content
    except (AttributeError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Patcher
# ---------------------------------------------------------------------------


def patch_openai() -> bool:
    """
    Monkey-patch the OpenAI client to auto-create spans.

    Returns True if patching succeeded, False if openai is not installed.
    """
    try:
        import openai  # noqa: F401
        from openai.resources.chat import completions as chat_completions_mod
    except ImportError:
        return False

    # Avoid double-patching
    if getattr(chat_completions_mod.Completions.create, "_pw_patched", False):
        return True

    original_create = chat_completions_mod.Completions.create
    original_acreate = chat_completions_mod.AsyncCompletions.create

    def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])
        t0 = time.time()

        active_run = _current_run.get()
        parent_span = _current_span.get()

        s = Span(
            run_id=active_run.run_id if active_run else "auto",
            name=f"openai.chat.completions/{model}",
            parent_span_id=parent_span.span_id if parent_span else None,
            started_at=t0,
            status=SpanStatus.RUNNING,
            inputs={"messages": _serialize_messages(messages), "model": model},
            model=model,
            provider="openai",
            tags={"integration": "openai"},
        )
        collector = get_collector()
        collector.emit_span(s)
        token = _current_span.set(s)

        try:
            response = original_create(self, *args, **kwargs)
            s.status = SpanStatus.OK
            usage = getattr(response, "usage", None)
            if usage:
                s.tokens_in = usage.prompt_tokens
                s.tokens_out = usage.completion_tokens
                s.cost_usd = _estimate_cost(model, s.tokens_in, s.tokens_out or 0)
            s.outputs = {
                "content": _extract_text_from_response(response),
                "finish_reason": _safe_finish_reason(response),
            }
            return response
        except Exception as exc:
            s.status = SpanStatus.ERROR
            s.error = str(exc)
            raise
        finally:
            s.ended_at = time.time()
            collector.emit_span(s)
            _current_span.reset(token)

    async def patched_acreate(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])
        t0 = time.time()

        active_run = _current_run.get()
        parent_span = _current_span.get()

        s = Span(
            run_id=active_run.run_id if active_run else "auto",
            name=f"openai.chat.completions/{model}",
            parent_span_id=parent_span.span_id if parent_span else None,
            started_at=t0,
            status=SpanStatus.RUNNING,
            inputs={"messages": _serialize_messages(messages), "model": model},
            model=model,
            provider="openai",
            tags={"integration": "openai"},
        )
        collector = get_collector()
        collector.emit_span(s)
        token = _current_span.set(s)

        try:
            response = await original_acreate(self, *args, **kwargs)
            s.status = SpanStatus.OK
            usage = getattr(response, "usage", None)
            if usage:
                s.tokens_in = usage.prompt_tokens
                s.tokens_out = usage.completion_tokens
                s.cost_usd = _estimate_cost(model, s.tokens_in, s.tokens_out or 0)
            s.outputs = {
                "content": _extract_text_from_response(response),
                "finish_reason": _safe_finish_reason(response),
            }
            return response
        except Exception as exc:
            s.status = SpanStatus.ERROR
            s.error = str(exc)
            raise
        finally:
            s.ended_at = time.time()
            collector.emit_span(s)
            _current_span.reset(token)

    patched_create._pw_patched = True  # type: ignore[attr-defined]
    patched_acreate._pw_patched = True  # type: ignore[attr-defined]

    chat_completions_mod.Completions.create = patched_create  # type: ignore[method-assign]
    chat_completions_mod.AsyncCompletions.create = patched_acreate  # type: ignore[method-assign]
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_messages(messages: list[Any]) -> list[dict]:
    """Safely serialize OpenAI messages list."""
    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append({k: str(v)[:2000] for k, v in m.items()})
        else:
            result.append(
                {"role": getattr(m, "role", "?"), "content": str(getattr(m, "content", ""))[:2000]}
            )
    return result


def _safe_finish_reason(response: Any) -> str | None:
    try:
        return response.choices[0].finish_reason
    except (AttributeError, IndexError):
        return None
