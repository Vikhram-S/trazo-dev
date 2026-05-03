"""
examples/openai_chain.py
~~~~~~~~~~~~~~~~~~~~~~~~
Demonstrates Trazo with a real OpenAI-powered multi-step chain.

Works without an OpenAI key by using mocked responses by default.
Set OPENAI_API_KEY to use a real model.

Run:
    python examples/openai_chain.py
    trazo view
    trazo ui
"""
from __future__ import annotations

import os
import sys
import time
import random

# Add project root to path for local development
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import trazo as tz

# ── Init ────────────────────────────────────────────────────────────────────
tz.init()

# If OpenAI key is available, use real instrumentation
USE_REAL_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
if USE_REAL_OPENAI:
    tz.instrument_openai()
    import openai
    client = openai.OpenAI()


# ── Mocked LLM (no API key needed for demo) ─────────────────────────────────

MOCK_RESPONSES = [
    "The key insight is that transformer architectures scale well because attention mechanisms allow O(n²) interactions.",
    "Python's GIL limits true parallelism for CPU-bound tasks; use multiprocessing or Rust extensions instead.",
    "The main bottleneck in RAG pipelines is typically the retrieval step — dense retrieval > sparse for semantic queries.",
    "Structured output via function calling is 40% more reliable than prompt-engineering JSON responses.",
]


@tz.trace(name="llm.generate", tags={"tier": "llm"})
def mock_llm_call(prompt: str, model: str = "mock-gpt-4o") -> str:
    """Simulated LLM call with realistic latency and metadata."""
    # Get current span to inject metadata
    s = tz.get_current_span()
    if s:
        from trazo.tracer import SpanContext
        ctx = SpanContext(s)
        tokens_in = len(prompt.split()) * 1.3
        tokens_out = random.randint(50, 200)
        ctx.set_model(model, provider="mock")
        ctx.set_tokens(int(tokens_in), int(tokens_out))
        ctx.set_cost((tokens_in * 0.0025 + tokens_out * 0.010) / 1000)

    # Simulate network latency
    time.sleep(random.uniform(0.05, 0.25))
    return random.choice(MOCK_RESPONSES)


@tz.trace(name="chunk_document")
def chunk_document(text: str, chunk_size: int = 512) -> list[str]:
    """Split a document into overlapping chunks."""
    words = text.split()
    chunks = []
    stride = chunk_size // 2
    for i in range(0, len(words), stride):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks[:5]  # Cap for demo


@tz.trace(name="retrieve_context")
def retrieve_context(query: str, chunks: list[str]) -> list[str]:
    """Fake retrieval: return top 2 chunks (replace with real vector search)."""
    time.sleep(0.02)
    return chunks[:2]


@tz.trace(name="build_prompt")
def build_prompt(query: str, context_chunks: list[str]) -> str:
    context = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(context_chunks))
    return f"""You are a helpful technical assistant. Answer the question using the provided context.

Context:
{context}

Question: {query}

Answer concisely and accurately:"""


@tz.trace(name="extract_answer")
def extract_answer(raw_output: str) -> dict:
    """Post-process the LLM output into structured form."""
    return {
        "answer": raw_output.strip(),
        "word_count": len(raw_output.split()),
        "has_code": "```" in raw_output,
    }


# ── Pipeline ─────────────────────────────────────────────────────────────────

def run_rag_pipeline(query: str, document: str) -> dict:
    """Full RAG pipeline: chunk → retrieve → generate → extract."""

    # Step 1: Chunk
    chunks = chunk_document(document)

    # Step 2: Retrieve
    context = retrieve_context(query, chunks)

    # Step 3: Build prompt
    prompt = build_prompt(query, context)

    # Step 4: Generate
    if USE_REAL_OPENAI:
        with tz.span("openai.generate", inputs={"model": "gpt-4o"}):
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            raw = resp.choices[0].message.content or ""
    else:
        raw = mock_llm_call(prompt, model="gpt-4o-mini")

    # Step 5: Post-process
    result = extract_answer(raw)
    return result


# ── Main ─────────────────────────────────────────────────────────────────────

SAMPLE_DOC = """
Large language models (LLMs) are neural networks trained on massive text corpora.
They use transformer architectures with self-attention mechanisms that enable
parallel processing of tokens. The key innovation is the ability to learn
contextual representations that generalize across many downstream tasks.
Modern LLMs like GPT-4 and Claude use reinforcement learning from human feedback
(RLHF) to align outputs with human preferences. Retrieval-augmented generation
(RAG) extends LLMs by grounding responses in external knowledge bases,
significantly reducing hallucination rates. Vector databases like Pinecone,
Weaviate, and Chroma enable efficient semantic search over millions of documents.
The main challenges in production LLM systems are latency, cost, and consistency.
Structured output via function calling ensures deterministic response formats.
Fine-tuning on domain-specific data can reduce both cost and latency by 60-80%.
"""

QUERIES = [
    "What is retrieval-augmented generation and why does it reduce hallucinations?",
    "How do transformer architectures enable parallel processing?",
    "What are the main production challenges for LLM systems?",
]

if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print(Panel(
        f"[bold cyan]Trazo Demo[/bold cyan] — RAG Pipeline\n"
        f"[dim]Mode: {'Real OpenAI' if USE_REAL_OPENAI else 'Mocked (set OPENAI_API_KEY for real)'}[/dim]",
        border_style="cyan",
    ))

    # Run two pipeline executions so we can diff them
    for run_num in range(1, 3):
        query = QUERIES[run_num - 1]
        console.print(f"\n[bold]Run {run_num}:[/bold] [dim]{query[:60]}…[/dim]")

        with tz.run(f"rag_pipeline_v{run_num}", metadata={"query_idx": run_num}) as r:
            result = run_rag_pipeline(query, SAMPLE_DOC)
            console.print(f"  [green]✓[/green] {result['word_count']} words, run=[cyan]{r.run_id[:8]}[/cyan]")

    # Wait for flush
    from trazo.collector import get_collector
    get_collector().flush(timeout=3.0)

    console.print(
        "\n[bold]Done![/bold] Now try:\n"
        "  [cyan]trazo view[/cyan]              — list runs in terminal\n"
        "  [cyan]trazo diff [id1] [id2][/cyan]  — semantic diff\n"
        "  [cyan]trazo ui[/cyan]                — open browser DAG viewer\n"
    )
