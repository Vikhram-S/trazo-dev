"""
Trazo.integrations.ollama_patch
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Auto-instrumentation for the Ollama Python SDK.

Patches `ollama.Client.chat` and `ollama.Client.generate` (and async variants)
to automatically create spans with token counts, execution latency, and local model metadata.

Usage:
    import trazo as tz
    tz.instrument_ollama()  # Call once at startup
"""

from __future__ import annotations

import time
from typing import Any

from ..collector import get_collector
from ..models import Span, SpanStatus
from ..tracer import _current_run, _current_span


def patch_ollama() -> bool:
    """
    Monkey-patch the Ollama client to auto-create spans.
    Returns True if patching succeeded, False if ollama is not installed.
    """
    try:
        import ollama  # noqa: F401
        from ollama import AsyncClient, Client
    except ImportError:
        return False

    # Avoid double-patching
    if getattr(Client.chat, "_tz_patched", False):
        return True

    original_chat = Client.chat
    original_generate = Client.generate
    original_achat = AsyncClient.chat
    original_agenerate = AsyncClient.generate

    def patched_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])
        return _sync_wrapper(
            original_chat,
            self,
            f"ollama.chat/{model}",
            model,
            {"messages": _serialize_messages(messages)},
            *args,
            **kwargs,
        )

    def patched_generate(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        prompt = kwargs.get("prompt", "")
        return _sync_wrapper(
            original_generate,
            self,
            f"ollama.generate/{model}",
            model,
            {"prompt": str(prompt)[:2000]},
            *args,
            **kwargs,
        )

    async def patched_achat(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])
        return await _async_wrapper(
            original_achat,
            self,
            f"ollama.chat/{model}",
            model,
            {"messages": _serialize_messages(messages)},
            *args,
            **kwargs,
        )

    async def patched_agenerate(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        prompt = kwargs.get("prompt", "")
        return await _async_wrapper(
            original_agenerate,
            self,
            f"ollama.generate/{model}",
            model,
            {"prompt": str(prompt)[:2000]},
            *args,
            **kwargs,
        )

    patched_chat._tz_patched = True  # type: ignore[attr-defined]
    patched_generate._tz_patched = True  # type: ignore[attr-defined]
    patched_achat._tz_patched = True  # type: ignore[attr-defined]
    patched_agenerate._tz_patched = True  # type: ignore[attr-defined]

    Client.chat = patched_chat
    Client.generate = patched_generate
    AsyncClient.chat = patched_achat
    AsyncClient.generate = patched_agenerate

    return True


def _create_span(name: str, model: str, inputs: dict[str, Any]) -> Span:
    active_run = _current_run.get()
    parent_span = _current_span.get()
    return Span(
        run_id=active_run.run_id if active_run else "auto",
        name=name,
        parent_span_id=parent_span.span_id if parent_span else None,
        started_at=time.time(),
        status=SpanStatus.RUNNING,
        inputs=inputs,
        model=model,
        provider="ollama",
        tags={"integration": "ollama", "local": "true"},
        cost_usd=0.0,  # Local execution is free!
    )


def _sync_wrapper(
    original_func: Any,
    self: Any,
    span_name: str,
    model: str,
    inputs: dict[str, Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    s = _create_span(span_name, model, inputs)
    collector = get_collector()
    collector.emit_span(s)
    token = _current_span.set(s)

    try:
        response = original_func(self, *args, **kwargs)
        s.status = SpanStatus.OK

        # Ollama provides eval_count (output) and prompt_eval_count (input)
        if isinstance(response, dict):
            s.tokens_in = response.get("prompt_eval_count", 0)
            s.tokens_out = response.get("eval_count", 0)

            if "message" in response:
                s.outputs = {"content": response["message"].get("content", "")}
            elif "response" in response:
                s.outputs = {"content": response.get("response", "")}

        return response
    except Exception as exc:
        s.status = SpanStatus.ERROR
        s.error = str(exc)
        raise
    finally:
        s.ended_at = time.time()
        collector.emit_span(s)
        _current_span.reset(token)


async def _async_wrapper(
    original_func: Any,
    self: Any,
    span_name: str,
    model: str,
    inputs: dict[str, Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    s = _create_span(span_name, model, inputs)
    collector = get_collector()
    collector.emit_span(s)
    token = _current_span.set(s)

    try:
        response = await original_func(self, *args, **kwargs)
        s.status = SpanStatus.OK

        if isinstance(response, dict):
            s.tokens_in = response.get("prompt_eval_count", 0)
            s.tokens_out = response.get("eval_count", 0)

            if "message" in response:
                s.outputs = {"content": response["message"].get("content", "")}
            elif "response" in response:
                s.outputs = {"content": response.get("response", "")}

        return response
    except Exception as exc:
        s.status = SpanStatus.ERROR
        s.error = str(exc)
        raise
    finally:
        s.ended_at = time.time()
        collector.emit_span(s)
        _current_span.reset(token)


def _serialize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append({"role": m.get("role", "?"), "content": str(m.get("content", ""))[:2000]})
        else:
            result.append(
                {"role": getattr(m, "role", "?"), "content": str(getattr(m, "content", ""))[:2000]}
            )
    return result
