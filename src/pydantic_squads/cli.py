"""`pydantic-squads` command-line entry point.

Currently just `trace`, the local trace viewer for a cycle recorded by
`ProductSquad(trace_dir=...)` (ADR 0006). Needs the `ai` extra (to read a
trace file's spans) and the `observability` extra (`rich`, to render them);
both are imported lazily so importing this module alone never requires
either.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TRACE_DIR = "traces"
DEFAULT_SLOW_THRESHOLD_MS = 5000.0
_HX_MISSING_SOURCE = "does not exist in the knowledge base"


@dataclass
class AgentMetrics:
    """Summed `model_call` span metrics for one agent, over a cycle."""

    agent: str
    duration_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class Report:
    """Everything `pydantic-squads trace` shows for one cycle."""

    cycle_id: str
    spans: list[Any] = field(default_factory=list)
    agent_metrics: list[AgentMetrics] = field(default_factory=list)
    slow_spans: list[Any] = field(default_factory=list)
    hx_retries: list[Any] = field(default_factory=list)
    po_send_backs: list[Any] = field(default_factory=list)
    pending_approvals: list[Any] = field(default_factory=list)
    cycle_input_tokens: int = 0
    over_budget_cycle: bool = False
    over_budget_spans: list[Any] = field(default_factory=list)


def build_report(
    cycle_id: str,
    trace_dir: Path | str,
    *,
    budget_tokens: int | None = None,
    slow_threshold_ms: float = DEFAULT_SLOW_THRESHOLD_MS,
) -> Report:
    """Build a diagnostic report for one cycle from its trace file.

    Pure data in, data out — no LLM call, no terminal output — so it's
    testable on its own. Needs the `ai` extra to read `Span`/`load_cycle`.
    """
    from pydantic_squads.product.observability import load_cycle

    _header, raw_spans, _snapshot = load_cycle(trace_dir, cycle_id)
    spans = sorted(raw_spans, key=lambda s: s.started_at)

    metrics: dict[str, AgentMetrics] = {}
    for span in spans:
        if span.operation != "model_call":
            continue
        m = metrics.setdefault(span.agent, AgentMetrics(agent=span.agent))
        m.duration_ms += span.duration_ms
        m.input_tokens += span.input_tokens or 0
        m.output_tokens += span.output_tokens or 0
        m.cost_usd += span.cost_usd or 0.0

    slow_spans = [s for s in spans if s.duration_ms > slow_threshold_ms]
    hx_retries = [
        s
        for s in spans
        if s.agent == "hx" and s.status == "retry" and s.detail and _HX_MISSING_SOURCE in s.detail
    ]
    po_send_backs = [s for s in spans if s.agent == "product_owner" and s.output_type == "SendBack"]
    resolved_tool_call_ids = {s.tool_call_id for s in spans if s.operation == "approval_resolution"}
    pending_approvals = [
        s
        for s in spans
        if s.status == "awaiting_approval"
        and s.tool_call_id is not None
        and s.tool_call_id not in resolved_tool_call_ids
    ]

    cycle_input_tokens = sum(s.input_tokens or 0 for s in spans if s.operation == "model_call")
    over_budget_cycle = budget_tokens is not None and cycle_input_tokens > budget_tokens
    over_budget_spans = (
        [s for s in spans if s.operation == "model_call" and (s.input_tokens or 0) > budget_tokens]
        if budget_tokens is not None
        else []
    )

    return Report(
        cycle_id=cycle_id,
        spans=spans,
        agent_metrics=sorted(metrics.values(), key=lambda m: m.agent),
        slow_spans=slow_spans,
        hx_retries=hx_retries,
        po_send_backs=po_send_backs,
        pending_approvals=pending_approvals,
        cycle_input_tokens=cycle_input_tokens,
        over_budget_cycle=over_budget_cycle,
        over_budget_spans=over_budget_spans,
    )


def _span_depth(span: Any, spans_by_id: dict[str, Any]) -> int:
    depth = 0
    parent_id = span.parent_span_id
    while parent_id is not None:
        depth += 1
        parent = spans_by_id.get(parent_id)
        parent_id = parent.parent_span_id if parent is not None else None
    return depth


def print_report(report: Report) -> None:
    """Render a `Report` with `rich`. Needs the `observability` extra."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    spans_by_id = {s.span_id: s for s in report.spans}
    max_duration = max((s.duration_ms for s in report.spans), default=0.0) or 1.0

    console.print(f"[bold]Cycle {report.cycle_id}[/bold]")

    timeline = Table(title="Timeline")
    timeline.add_column("Span")
    timeline.add_column("Agent")
    timeline.add_column("Status")
    timeline.add_column("Duration")
    for span in report.spans:
        indent = "  " * _span_depth(span, spans_by_id)
        bar_width = max(1, round((span.duration_ms / max_duration) * 20))
        timeline.add_row(f"{indent}{span.operation}", span.agent, span.status, f"{'█' * bar_width} {span.duration_ms:.0f}ms")
    console.print(timeline)

    metrics_table = Table(title="Per-agent metrics")
    metrics_table.add_column("Agent")
    metrics_table.add_column("Duration (ms)")
    metrics_table.add_column("Input tokens")
    metrics_table.add_column("Output tokens")
    metrics_table.add_column("Cost (USD)")
    for m in report.agent_metrics:
        metrics_table.add_row(m.agent, f"{m.duration_ms:.0f}", str(m.input_tokens), str(m.output_tokens), f"{m.cost_usd:.4f}")
    console.print(metrics_table)

    console.print("[bold]Diagnostics[/bold]")
    console.print(f"Slow spans: {len(report.slow_spans)}")
    for s in report.slow_spans:
        console.print(f"  - {s.operation} ({s.agent}): {s.duration_ms:.0f}ms")
    console.print(f"HX retries citing a missing source: {len(report.hx_retries)}")
    for s in report.hx_retries:
        console.print(f"  - {s.detail}")
    console.print(f"Product Owner send-backs: {len(report.po_send_backs)}")
    console.print(f"Pending approvals: {len(report.pending_approvals)}")
    for s in report.pending_approvals:
        console.print(f"  - {s.operation} ({s.agent})")
    if report.over_budget_cycle:
        console.print(f"[red]Cycle input tokens ({report.cycle_input_tokens}) exceed budget[/red]")
    for s in report.over_budget_spans:
        console.print(f"[red]  - {s.operation} ({s.agent}): {s.input_tokens} input tokens[/red]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pydantic-squads")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trace_parser = subparsers.add_parser("trace", help="Inspect a cycle's recorded trace")
    trace_parser.add_argument("cycle_id")
    trace_parser.add_argument(
        "--trace-dir", default=os.environ.get("PYDANTIC_SQUADS_TRACE_DIR", DEFAULT_TRACE_DIR)
    )
    trace_parser.add_argument("--budget-tokens", type=int, default=None)
    trace_parser.add_argument("--slow-threshold-ms", type=float, default=DEFAULT_SLOW_THRESHOLD_MS)

    args = parser.parse_args(argv)

    try:
        report = build_report(
            args.cycle_id,
            args.trace_dir,
            budget_tokens=args.budget_tokens,
            slow_threshold_ms=args.slow_threshold_ms,
        )
        print_report(report)
    except ImportError:
        print("pydantic-squads trace needs: pip install 'pydantic-squads[ai,observability]'", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"pydantic-squads trace: {exc}", file=sys.stderr)
        return 1
    return 0
