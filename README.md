# 🧵 Trazo

<div align="center">

**Execution tracer and semantic diff engine for LLM agent pipelines.**

*Know exactly why your agent did what it did — and how it changed.*

[![CI](https://github.com/trazo-dev/trazo/actions/workflows/ci.yml/badge.svg)](https://github.com/trazo-dev/trazo/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/trazo-dev.svg)](https://badge.fury.io/py/trazo-dev)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Downloads](https://static.pepy.tech/badge/trazo-dev/month)](https://pepy.tech/project/trazo-dev)
[![Discord](https://img.shields.io/discord/000000000?logo=discord&label=Discord)](https://discord.gg/Trazo)

</div>

---

## The Problem

You're building an LLM pipeline. It worked yesterday. Today it's producing different answers, costing more, and you have no idea which call changed. You're staring at raw JSON logs and guessing.

**Trazo fixes this.**

```
Before Trazo:              After Trazo:
─────────────────              ───────────────
print(response)         →      trazo view abc123
grep through logs       →      trazo diff abc123 def456
re-run everything       →      trazo replay abc123 --span xyz
open Datadog ($$$)      →      trazo ui  (local, free, instant)
```

---

## What Trazo Does

- 🔍 **Traces** every function call in your pipeline with zero boilerplate
- 📊 **Visualizes** execution as a DAG — see parent/child spans, durations, costs
- 🔀 **Semantically diffs** two runs — detects *what changed* and *how much*
- ⏮️ **Replays** any span with its exact original inputs (time-travel debugging)
- 💰 **Tracks** token counts and USD cost per span, per run
- 🔒 **Local-first** — all data stays on your machine, zero cloud dependencies
- ⚡ **Framework-agnostic** — works with OpenAI, Anthropic, raw HTTP, LangChain, any Python

---

## Quickstart

### Install

```bash
pip install trazo-dev

# For the web UI:
pip install "trazo-dev[ui]"
```

### Instrument in 3 lines

```python
import trazo as tz

tz.init()  # ← once, at startup
tz.instrument_ollama() # ← 100% local, no API keys!

@tz.trace  # ← on any function
def call_llm(prompt: str) -> str:
    # Use ollama, openai, anthropic, or any custom client
    return ollama.generate(model="phi3", prompt=prompt)["response"]

with tz.run("my_pipeline"):
    result = call_llm("Explain transformers in one sentence")
```

### See what happened

```bash
trazo view                    # list all runs
trazo view abc123             # inspect a specific run
trazo view abc123 --spans     # full span tree
trazo diff [id1] [id2]        # semantic diff between runs
trazo replay abc123           # re-execute with original inputs
trazo ui                      # open browser DAG viewer
```

---

## Core Features

### `@trazo.trace` — Automatic instrumentation

Decorate any function — sync or async — to capture inputs, outputs, timing, and errors:

```python
@trazo.trace
def retrieve_context(query: str, top_k: int = 5) -> list[str]:
    return vector_db.search(query, k=top_k)

@trazo.trace(name="llm.generate", tags={"tier": "primary"})
async def async_generate(messages: list[dict]) -> str:
    response = await openai_client.chat.completions.create(...)
    return response.choices[0].message.content
```

### `trazo.span()` — Fine-grained control

Use context managers for manual span control and LLM metadata injection:

```python
with trazo.run("rag_pipeline") as r:
    r.tag("experiment", "prompt_v3")

    with trazo.span("retrieve", inputs={"query": q}) as s:
        docs = vector_db.search(q)
        s.set_output({"doc_count": len(docs)})

    with trazo.span("generate") as s:
        s.set_model("gpt-4o")
        s.set_tokens(tokens_in=1240, tokens_out=380)
        s.set_cost(0.00412)
        response = llm.generate(docs, q)
```

### `trazo diff` — Semantic diff between runs

```
$ trazo diff abc123 def456

Comparing run_v1 against run_v2
Overall similarity: 71.3% — Similar with changes
Cost delta:    +$0.00234
Token delta:   +312
Latency delta: +480ms

╭──────────────────────────┬────────────┬────────────┬──────────┬──────────╮
│ Span                     │ Kind       │ Similarity │ Cost Δ   │ Token Δ  │
├──────────────────────────┼────────────┼────────────┼──────────┼──────────┤
│ retrieve_context         │ ≡ identical│ 99.2%      │ —        │ —        │
│ openai.chat/gpt-4o       │ ≠ diverged │ 54.1%      │ +$0.0021 │ +289     │
│ extract_answer           │ ≈ similar  │ 78.3%      │ —        │ —        │
│ new_validation_step      │ + added    │ 0.0%       │ +$0.0002 │ +23      │
╰──────────────────────────┴────────────┴────────────┴──────────┴──────────╯
```

### `trazo replay` — Time-travel debugging

Re-execute any span with its exact original inputs, with optional overrides:

```bash
# Replay with original inputs
trazo replay abc123def456

# Replay with a different model (A/B test)
trazo replay abc123def456 -o model=gpt-4o-mini

# Dry-run: print inputs without executing
trazo replay abc123def456 --dry-run
```

### `trazo ui` — Browser DAG viewer

```bash
trazo ui
# → http://localhost:7432
```

Visualize your full execution DAG with D3.js. Click any node to inspect inputs/outputs. Compare runs. Track cost trends over time.

### 🦙 Ollama & OpenAI Auto-instrumentation

Zero code changes — just call once at startup to automatically trace models with token counts, execution latency, and cost estimates:

```python
import trazo as tz

tz.init()

# 100% Local, API-free tracing
tz.instrument_ollama()
response = ollama.chat(model="phi3", messages=[...])

# Or cloud providers
tz.instrument_openai()
response = client.chat.completions.create(model="gpt-4o", messages=[...])
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Your Agent Code                              │
│   @trazo.trace  /  trazo.span()  /  trazo.aspan()                       │
└───────────────────────┬─────────────────────────────────────────┘
                        │ emit TraceEvent (non-blocking)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│              TraceCollector (singleton)                         │
│  Thread-safe queue → background flush worker                    │
│  Never blocks your agent's execution path                       │
└───────────────────┬─────────────────────────────────────────────┘
                    │ write
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              StorageEngine (SQLite, WAL mode)                   │
│  runs / spans / embeddings tables                               │
│  Zero external dependencies — stdlib only                       │
└───────┬───────────┴────────────────────────────────────────────-┘
        │                        │
        ▼                        ▼
┌────────────────┐   ┌────────────────────────────────────────────┐
│  CLI  (trazo)     │   │    Web UI  (FastAPI + D3.js)               │
│  trazo view       │   │    http://localhost:7432                    │
│  trazo diff       │   │    DAG viz · Span inspector · Diff panel   │
│  trazo replay     │   │                                            │
│  trazo export     │   │                                            │
└────────────────┘   └────────────────────────────────────────────┘
```

**Key design decisions:**

| Decision | Rationale |
|----------|-----------|
| SQLite storage | Zero setup, works offline, WAL mode for concurrent access |
| ContextVar propagation | Correct parent-child span linking across async boundaries |
| TF n-gram similarity | Semantic diff without requiring an ML model |
| Background flush worker | Tracing never blocks the critical path |
| Framework-agnostic | Monkey-patch integrations are opt-in, not required |

---

## Installation Options

```bash
# Minimal (CLI + tracing, no web UI)
pip install trazo-dev

# With web UI
pip install "trazo-dev[ui]"

# With real semantic embeddings (better diff quality)
pip install "trazo-dev[embeddings]"

# Everything
pip install "trazo-dev[ui,embeddings]"

# Development
pip install "trazo-dev[dev,ui]"
pre-commit install
```

---

## CLI Reference

```
trazo view [RUN_ID] [--spans] [--limit N] [--db PATH]
trazo diff RUN_A RUN_B [--show-identical] [--db PATH]
trazo replay SPAN_ID [-o KEY=VALUE ...] [--dry-run] [--db PATH]
trazo export RUN_ID [--format json|html] [-o PATH] [--db PATH]
trazo clean [--older-than DAYS] [--keep N] [--run ID] [--all] [--yes]
trazo ui [--host HOST] [--port PORT] [--db PATH]
```

Supports short IDs — you never need to type the full UUID.

---

## Python API Reference

```python
import trazo as tz

# Initialization
tz.init(db_path=None)
tz.instrument_ollama()
tz.instrument_openai()

# Tracing
@tz.trace                                 # sync decorator
@tz.trace(name="x", tags={"k": "v"})     # with options
async def fn(): ...                        # async supported automatically

# Context managers
with trazo.run("name", metadata={}) as r:    # top-level run
    r.tag("key", "value")

with trazo.span("name", inputs={}) as s:     # named span
    s.set_model("gpt-4o")
    s.set_tokens(100, 50)
    s.set_cost(0.00123)
    s.set_output({"result": ...})
    s.tag("key", "value")

async with trazo.aspan("name") as s:         # async span
    ...

# Inspection
trazo.get_current_span()                     # active Span | None
trazo.get_current_run()                      # active Run | None
```

---

## Extending Trazo

### Custom storage backend

```python
from trazo.storage import StorageEngine
from trazo.collector import get_collector

# Use a custom database path
storage = StorageEngine(db_path="/data/my_project/traces.db")
get_collector().configure(storage)
```

### Adding an integration

```python
# Trazo/integrations/anthropic_patch.py
from trazo.tracer import _current_span, _current_run
from trazo.models import Span, SpanStatus

def patch_anthropic():
    import anthropic
    original_create = anthropic.resources.Messages.create
    def patched_create(self, *args, **kwargs):
        # ... same pattern as openai_patch.py
        pass
    anthropic.resources.Messages.create = patched_create
```

### MCP (Model Context Protocol) server

```bash
# Expose your traces as an MCP tool
pip install "trazo-dev[mcp]"   # coming in v0.2
trazo mcp-serve
```

---

## Roadmap

- [x] Core tracing engine (`@trazo.trace`, `trazo.span()`, `trazo.aspan()`)
- [x] SQLite storage with WAL mode
- [x] Semantic diff engine (n-gram TF similarity)
- [x] Time-travel replay
- [x] Rich terminal CLI (`trazo view`, `trazo diff`, `trazo replay`, `trazo export`)
- [x] Web UI with D3.js DAG visualization
- [x] OpenAI auto-instrumentation
- [x] CI: Python 3.10-3.12, Windows/macOS/Linux
- [ ] Anthropic auto-instrumentation
- [x] Ollama auto-instrumentation
- [ ] MCP server for Claude Desktop / Cursor integration
- [ ] LangChain callback integration
- [ ] Real semantic embeddings via `sentence-transformers`
- [ ] GitHub Actions diff annotations (fail CI if similarity < threshold)
- [ ] VS Code extension
- [ ] `trazo watch` — live terminal dashboard

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

```bash
git clone https://github.com/trazo-dev/trazo
cd Trazo
pip install -e ".[dev,ui]"
pre-commit install
pytest tests/ -v
```

**Good first issues:** look for the `good first issue` label.

---

## Why Trazo Will Reach 1,000 Stars

| Reason | Detail |
|--------|--------|
| **Universal pain** | Every team building LLM apps hits the "why did this change" problem |
| **30-second onboarding** | `pip install` + one decorator = full traces |
| **No API key needed** | Natively supports Ollama so you can build and trace pipelines completely offline and for free |
| **Visual demo hook** | The DAG viewer is screenshot-worthy and shareable |
| **Zero lock-in** | SQLite, MIT license, no cloud, no vendor dependency |
| **Framework agnostic** | Works with whatever stack you already use |

---

## License

MIT © 2026 Trazo Contributors

---

<div align="center">

**[⭐ Star on GitHub](https://github.com/trazo-dev/trazo)** · **[📖 Docs](https://trazo-dev.dev)** · **[💬 Discord](https://discord.gg/Trazo)** · **[🐛 Issues](https://github.com/trazo-dev/trazo/issues)**

*Built with love for everyone debugging LLM agents at 2am.*

</div>
