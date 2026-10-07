"""Simulates a multi-agent squad run and prints its timeline as a Gantt chart."""

import asyncio
import time

from pydantic_squads import SpanCollector, TerminalGantt, track_span


def simulated_spans() -> None:
    """Offsets and durations in ms, as replayed from a trace."""
    with SpanCollector() as collector:
        # Growth PM
        collector.record_with_offset("agent_run", "growth_pm", 0, 113.968)
        collector.record_with_offset("  model_call", "growth_pm", 0, 6.519)
        collector.record_with_offset("  tool:consult_hx", "growth_pm", 6.519, 80.222)
        collector.record_with_offset("  tool:read_note", "growth_pm", 86.741, 20.708)
        # NX, in parallel and 20ms later, with a retry
        collector.record_with_offset("agent_run", "nx", 20, 106.685)
        collector.record_with_offset("  model_call", "nx", 20, 5.586, status="retry")
        collector.record_with_offset("  tool:search_notes", "nx", 25.586, 36)
        collector.record_with_offset("  model_call", "nx", 61.586, 47.368)
        # HX answering queries
        collector.record_with_offset("agent_run", "hx", 10, 50.0)
        collector.record_with_offset("  query_vault", "hx", 10, 15.0)
    collector.render_gantt(width=120)


async def tracked_calls() -> None:
    """Spans collected automatically with the decorator and the context manager."""
    collector = SpanCollector()

    @track_span(collector, "growth_pm", "model_call")
    async def call_model() -> None:
        await asyncio.sleep(0.02)

    @track_span(collector, "hx")
    def consult() -> None:
        time.sleep(0.05)

    await call_model()
    with collector.span("tool:read_note", agent="growth_pm"):
        consult()
    collector.render_gantt(width=100)


if __name__ == "__main__":
    simulated_spans()
    asyncio.run(tracked_calls())
    gantt = TerminalGantt(width=80, use_colors=False)  # plain output for logs
    gantt.add_span("manual", 0, 10, agent="po")
    gantt.print()
