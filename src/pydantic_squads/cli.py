"""`pydantic-squads` command-line entry point.

`trace` is the local trace viewer for a cycle recorded by
`ProductSquad(trace_dir=...)` (ADR 0006). `chat` is a terminal session
with the product squad (ADR 0017). Both need the `ai` extra and the
`observability` extra (`rich`); they are imported lazily, so importing
this module alone never requires either.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Iterable
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
    calls: int = 0
    retried: int = 0
    models: list[str] = field(default_factory=list)  # every model that answered for this agent


@dataclass
class Report:
    """Everything `pydantic-squads trace` shows for one cycle."""

    cycle_id: str
    spans: list[Any] = field(default_factory=list)
    agent_metrics: list[AgentMetrics] = field(default_factory=list)
    slow_spans: list[Any] = field(default_factory=list)
    hx_retries: list[Any] = field(default_factory=list)
    brief_rejections: list[Any] = field(default_factory=list)
    designer_send_backs: list[Any] = field(default_factory=list)
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
    return report_from_spans(
        cycle_id, raw_spans, budget_tokens=budget_tokens, slow_threshold_ms=slow_threshold_ms
    )


def report_from_spans(
    cycle_id: str,
    raw_spans: Iterable[Any],
    *,
    budget_tokens: int | None = None,
    slow_threshold_ms: float = DEFAULT_SLOW_THRESHOLD_MS,
) -> Report:
    """The same report from spans already in hand, such as a running squad's (`ProductSquad.spans`)."""
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
        m.calls += 1
        m.retried += span.status == "retry"
        if span.model and span.model not in m.models:
            m.models.append(span.model)

    # A "squad" span is a whole step of the request, as long as the runs inside it: not a slow call.
    slow_spans = [s for s in spans if s.duration_ms > slow_threshold_ms and s.agent != "squad"]
    hx_retries = [
        s
        for s in spans
        if s.agent == "hx" and s.status == "retry" and s.detail and _HX_MISSING_SOURCE in s.detail
    ]
    brief_rejections = [s for s in spans if s.output_type == "BriefRejection"]
    designer_send_backs = [s for s in spans if s.agent == "designer" and s.output_type == "SendBack"]
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
        brief_rejections=brief_rejections,
        designer_send_backs=designer_send_backs,
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
    metrics_table.add_column("Model")
    metrics_table.add_column("Calls")
    metrics_table.add_column("Duration (ms)")
    metrics_table.add_column("Input tokens")
    metrics_table.add_column("Output tokens")
    metrics_table.add_column("Cost (USD)")
    for m in report.agent_metrics:
        metrics_table.add_row(
            m.agent,
            ", ".join(m.models) or "-",
            str(m.calls),
            f"{m.duration_ms:.0f}",
            str(m.input_tokens),
            str(m.output_tokens),
            f"{m.cost_usd:.4f}",
        )
    console.print(metrics_table)

    console.print("[bold]Diagnostics[/bold]")
    console.print(f"Slow spans: {len(report.slow_spans)}")
    for s in report.slow_spans:
        console.print(f"  - {s.operation} ({s.agent}): {s.duration_ms:.0f}ms")
    console.print(f"HX retries citing a missing source: {len(report.hx_retries)}")
    for s in report.hx_retries:
        console.print(f"  - {s.detail}")
    console.print(f"Brief rejections: {len(report.brief_rejections)}")
    for s in report.brief_rejections:
        console.print(f"  - {s.operation} ({s.agent})")
    console.print(f"Designer send-backs: {len(report.designer_send_backs)}")
    console.print(f"Pending approvals: {len(report.pending_approvals)}")
    for s in report.pending_approvals:
        console.print(f"  - {s.operation} ({s.agent})")
    if report.over_budget_cycle:
        console.print(f"[red]Cycle input tokens ({report.cycle_input_tokens}) exceed budget[/red]")
    for s in report.over_budget_spans:
        console.print(f"[red]  - {s.operation} ({s.agent}): {s.input_tokens} input tokens[/red]")


_EXTRAS_HINT = "pip install 'pydantic-squads[ai,observability]'"


def role_models(
    pm_model: str | None,
    hx_model: str | None,
    pairs: Iterable[str],
    committee: Iterable[str],
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """The role -> model map of `chat`: `base`, then the PMs' and HX's shorthands, then each `ROLE=MODEL` pair."""
    models = dict(base or {})
    if pm_model:
        models.update(dict.fromkeys(committee, pm_model))
    if hx_model:
        models["hx"] = hx_model
    for pair in pairs:
        role_id, _, model = pair.partition("=")
        models[role_id.strip()] = model.strip()
    return models


def _chat(args: argparse.Namespace) -> int:
    """Run `pydantic-squads chat`: a terminal session with the product squad (ADR 0017)."""
    try:
        from pydantic_ai import UsageLimits

        from pydantic_squads.product import COMMITTEE_ROLES, MarkdownKnowledgeBase
        from pydantic_squads.product.assembly import ProductSquad
        from pydantic_squads.product.chat import ChatSession
        from pydantic_squads.product.claude_code import RECOMMENDED_MODEL, RECOMMENDED_ROLE_MODELS
    except ImportError:
        print(f"pydantic-squads chat needs: {_EXTRAS_HINT}", file=sys.stderr)
        return 1

    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"pydantic-squads chat: '{vault}' is not a folder of notes", file=sys.stderr)
        return 1
    # No --model: the recommended Claude Code setup, which the other model options can still adjust.
    model = args.model or RECOMMENDED_MODEL
    models = role_models(
        args.pm_model, args.hx_model, args.role_model, COMMITTEE_ROLES, None if args.model else RECOMMENDED_ROLE_MODELS
    )
    if any(m.startswith("claude-code") for m in (model, *models.values())) and shutil.which("claude") is None:
        print(
            "pydantic-squads chat: Claude Code was not found. Install it and log in with `claude`, "
            "or pass --model with another Pydantic AI model.",
            file=sys.stderr,
        )
        return 1
    context = Path(args.context).read_text(encoding="utf-8") if Path(args.context).is_file() else args.context
    skills_dirs = [Path(d) for d in args.skills_dir] if args.skills or args.skills_dir else None

    def make_squad() -> Any:
        return ProductSquad(
            MarkdownKnowledgeBase(vault),
            model=model,
            models=models,
            context=context,
            language=args.language,
            skills_dirs=skills_dirs,
            usage_limits=UsageLimits(request_limit=args.request_limit) if args.request_limit else None,
            trace_dir=args.trace_dir,
        )

    try:
        session = ChatSession(make_squad)
    except ValueError as exc:  # a --role-model naming a role the squad does not have
        print(f"pydantic-squads chat: {exc}", file=sys.stderr)
        return 1
    exceptions = ", ".join(f"{role_id} on {m}" for role_id, m in models.items())
    session.console.print(f"Model: {model}" + (f" (except {exceptions})" if exceptions else ""))
    session.run()
    return 0


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

    chat_parser = subparsers.add_parser("chat", help="Talk to the product squad in a terminal")
    chat_parser.add_argument("vault", help="a folder of markdown notes: the knowledge base")
    chat_parser.add_argument("--context", default="", help="what the product is, or a path to a file saying so")
    chat_parser.add_argument(
        "--model", default=None, help="model for every role not named; omit for the recommended Claude Code setup"
    )
    chat_parser.add_argument("--pm-model", default=None, help="model for the three PMs")
    chat_parser.add_argument("--hx-model", default=None, help="model for HX")
    chat_parser.add_argument(
        "--role-model", action="append", default=[], metavar="ROLE=MODEL", help="model for one role; repeatable"
    )
    chat_parser.add_argument("--language", default="en", choices=["en", "pt-BR"])
    chat_parser.add_argument(
        "--trace-dir",
        default=os.environ.get("PYDANTIC_SQUADS_TRACE_DIR"),
        help="record each cycle's trace here (needed by /resume)",
    )
    chat_parser.add_argument("--request-limit", type=int, default=None, help="model requests allowed per agent run")
    chat_parser.add_argument("--skills", action="store_true", help="give the roles the library's own skills")
    chat_parser.add_argument(
        "--skills-dir", action="append", default=[], metavar="DIR", help="a folder of more skills; repeatable"
    )

    args = parser.parse_args(argv)
    if args.command == "chat":
        return _chat(args)

    try:
        report = build_report(
            args.cycle_id,
            args.trace_dir,
            budget_tokens=args.budget_tokens,
            slow_threshold_ms=args.slow_threshold_ms,
        )
        print_report(report)
    except ImportError:
        print(f"pydantic-squads trace needs: {_EXTRAS_HINT}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"pydantic-squads trace: {exc}", file=sys.stderr)
        return 1
    return 0
