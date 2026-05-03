"""
examples/multi_agent.py
~~~~~~~~~~~~~~~~~~~~~~~
Demonstrates Trazo with a multi-agent orchestration pattern.

Two agents collaborate: a Planner and an Executor.
All spans are nested correctly via ContextVar propagation.

Run:
    python examples/multi_agent.py
    trazo view
"""
from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import trazo as tz

tz.init()


# ── Agent base class ─────────────────────────────────────────────────────────

class Agent:
    def __init__(self, name: str, model: str = "mock-gpt-4o") -> None:
        self.name = name
        self.model = model

    def _llm(self, system: str, user: str) -> str:
        """Mocked LLM call."""
        current = tz.get_current_span()
        if current:
            ctx = tz.tracer.SpanContext(current)
            toks_in = len((system + user).split())
            toks_out = random.randint(30, 150)
            ctx.set_model(self.model)
            ctx.set_tokens(toks_in, toks_out)
            ctx.set_cost((toks_in * 0.0025 + toks_out * 0.010) / 1000)
        time.sleep(random.uniform(0.03, 0.12))
        responses = [
            "Break task into: 1) gather data 2) analyze 3) synthesize report",
            "Step 1 complete. Found 3 relevant sources with 94% relevance.",
            "Analysis complete: primary factor is increased adoption rate +23% YoY.",
            "Report synthesized. Key findings: strong growth, recommend scale-up.",
        ]
        return random.choice(responses)


class PlannerAgent(Agent):
    @tz.trace(name="planner.create_plan", tags={"agent": "planner"})
    def create_plan(self, goal: str) -> list[str]:
        """Decompose a goal into executable steps."""
        with tz.span("planner.llm_call", inputs={"goal": goal}) as s:
            s.set_model(self.model)
            raw = self._llm(
                system="You are a task planner. Decompose goals into 3-5 concrete steps.",
                user=f"Goal: {goal}",
            )
        steps = [f"Step {i+1}: {raw.split('.')[0] if '.' in raw else raw}" for i in range(3)]
        return steps

    @tz.trace(name="planner.validate_plan", tags={"agent": "planner"})
    def validate_plan(self, steps: list[str]) -> bool:
        """Verify the plan is feasible."""
        time.sleep(0.02)
        return len(steps) >= 2


class ExecutorAgent(Agent):
    @tz.trace(name="executor.run_step", tags={"agent": "executor"})
    def run_step(self, step: str, context: dict) -> dict:
        """Execute a single plan step."""
        with tz.span("executor.tool_call", inputs={"step": step, "tool": "web_search"}):
            time.sleep(random.uniform(0.02, 0.08))
            tool_result = f"Found data for: {step[:30]}"

        with tz.span("executor.llm_synthesize", inputs={"step": step}) as s:
            s.set_model(self.model)
            result = self._llm(
                system="You are an executor. Complete this step and report results.",
                user=f"{step}\n\nTool result: {tool_result}",
            )

        return {"step": step, "result": result, "status": "done"}

    @tz.trace(name="executor.aggregate_results", tags={"agent": "executor"})
    def aggregate_results(self, step_results: list[dict]) -> str:
        """Combine step results into final output."""
        summaries = [r["result"][:50] for r in step_results]
        return f"Aggregated {len(step_results)} steps: " + " | ".join(summaries[:2])


# ── Orchestrator ─────────────────────────────────────────────────────────────

@tz.trace(name="orchestrate", tags={"pipeline": "multi_agent"})
def orchestrate(goal: str) -> str:
    planner = PlannerAgent("planner")
    executor = ExecutorAgent("executor")

    # Plan phase
    with tz.span("phase.planning", inputs={"goal": goal}):
        plan = planner.create_plan(goal)
        valid = planner.validate_plan(plan)
        if not valid:
            raise ValueError("Plan validation failed")

    # Execute phase
    results = []
    with tz.span("phase.execution", inputs={"step_count": len(plan)}):
        for step in plan:
            result = executor.run_step(step, context={"goal": goal})
            results.append(result)

    # Synthesize
    with tz.span("phase.synthesis"):
        final = executor.aggregate_results(results)

    return final


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rich.console import Console
    console = Console()

    goals = [
        "Research and summarize the latest developments in quantum computing",
        "Analyze market trends for AI developer tools in 2026",
    ]

    for goal in goals:
        console.print(f"\n[bold cyan]Goal:[/bold cyan] {goal[:60]}…")
        with tz.run("multi_agent_pipeline", metadata={"goal": goal}) as r:
            output = orchestrate(goal)
            console.print(f"  [green]✓[/green] Complete  run=[cyan]{r.run_id[:8]}[/cyan]")
            console.print(f"  [dim]{output[:80]}[/dim]")

    from trazo.collector import get_collector
    get_collector().flush(timeout=3.0)
    console.print("\n[dim]Try: trazo view · trazo diff · trazo ui[/dim]\n")
