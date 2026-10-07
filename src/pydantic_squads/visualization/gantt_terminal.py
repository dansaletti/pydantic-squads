"""Terminal Gantt charts for execution spans (standard library only).

    from pydantic_squads.visualization import TerminalGantt

    gantt = TerminalGantt(width=120)
    gantt.add_span("model_call", 0, 6.519, agent="growth_pm", status="ok")
    gantt.add_span("tool:consult_hx", 6.519, 80.222, agent="growth_pm")
    gantt.print()
"""

import functools
import inspect
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class Span:
    """An execution span."""

    name: str
    start_ms: float
    duration_ms: float
    agent: Optional[str] = None
    status: str = "ok"  # ok, retry, error, awaiting_approval

    @property
    def end_ms(self) -> float:
        return self.start_ms + self.duration_ms


class TerminalGantt:
    """Renders Gantt charts in the terminal with Unicode and ANSI colors."""

    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "purple": "\033[95m",
        "cyan": "\033[96m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "blue": "\033[94m",
        "magenta": "\033[35m",
        "gray": "\033[90m",
    }

    AGENT_COLORS = {
        "growth_pm": "purple",
        "pm_growth": "purple",
        "nx": "green",
        "hx": "cyan",
        "po": "yellow",
        "designer": "blue",
        "design": "blue",
        "social": "magenta",
    }

    STATUS_SYMBOLS = {"ok": "✓", "retry": "⟳", "error": "✗", "awaiting_approval": "⏸"}
    STATUS_COLORS = {"retry": "yellow", "error": "red", "awaiting_approval": "magenta"}

    def __init__(
        self,
        width: int = 120,
        show_ms: bool = True,
        use_colors: bool = True,
        collapse_gaps_ms: Optional[float] = None,
    ):
        """
        Args:
            width: Terminal width in characters.
            show_ms: Show timestamps in ms.
            use_colors: Use ANSI colors (disable if the terminal lacks support).
            collapse_gaps_ms: Idle stretches with no span running, longer than this,
                are shortened to this length (a cycle resumed hours later stays readable).
        """
        self.width = width
        self.show_ms = show_ms
        self.use_colors = use_colors
        self.collapse_gaps_ms = collapse_gaps_ms
        self.spans: list[Span] = []

    def add_span(
        self,
        name: str,
        start_ms: float,
        duration_ms: float,
        agent: Optional[str] = None,
        status: str = "ok",
    ) -> None:
        """Add a span to the chart."""
        self.spans.append(Span(name, start_ms, duration_ms, agent, status))

    def add_spans_from_trace(self, trace_dict: dict) -> None:
        """Add the spans of a trace dict (``{"spans": [{"name", "start", "duration", ...}]}``)."""
        for span_data in trace_dict.get("spans", []):
            self.add_span(
                name=span_data.get("name", "unknown"),
                start_ms=float(span_data.get("start", 0)),
                duration_ms=float(span_data.get("duration", 0)),
                agent=span_data.get("agent"),
                status=span_data.get("status", "ok"),
            )

    @classmethod
    def from_jsonl(cls, path: "str | Path", **kwargs: Any) -> "TerminalGantt":
        """Build a chart from a ``pydantic-squads`` trace file (``Span`` lines, ADR 0006).

        Child spans are indented under their parent. Extra kwargs go to the constructor.
        """
        records = []
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") == "Span":
                records.append(row["data"])
        parents = {r["span_id"]: r.get("parent_span_id") for r in records}

        def depth(span_id: str) -> int:
            level = 0
            while parents.get(span_id):
                span_id = parents[span_id]
                level += 1
            return level

        def millis(iso: str) -> float:
            return datetime.fromisoformat(iso).timestamp() * 1000

        gantt = cls(**kwargs)
        origin = min((millis(r["started_at"]) for r in records), default=0.0)
        for r in records:
            gantt.add_span(
                "  " * depth(r["span_id"]) + r["operation"],
                millis(r["started_at"]) - origin,
                r["duration_ms"],
                agent=r.get("agent"),
                status=r.get("status", "ok"),
            )
        return gantt

    def _collapsed(self) -> list[Span]:
        """Spans with idle gaps longer than ``collapse_gaps_ms`` shortened."""
        if self.collapse_gaps_ms is None:
            return self.spans
        gap, shift, covered_until = self.collapse_gaps_ms, 0.0, None
        out = []
        for span in sorted(self.spans, key=lambda s: s.start_ms):
            if covered_until is not None and span.start_ms - covered_until > gap:
                shift += span.start_ms - covered_until - gap
            covered_until = max(covered_until or span.end_ms, span.end_ms)
            out.append(replace(span, start_ms=span.start_ms - shift))
        return out

    def _color(self, color_name: str) -> str:
        if not self.use_colors:
            return ""
        return self.COLORS.get(color_name, "")

    def _reset(self) -> str:
        return self.COLORS["reset"] if self.use_colors else ""

    def _get_agent_color(self, agent: Optional[str], status: str = "ok") -> str:
        if status in self.STATUS_COLORS:
            return self._color(self.STATUS_COLORS[status])
        if agent:
            return self._color(self.AGENT_COLORS.get(agent.lower(), "cyan"))
        return self._color("cyan")

    def _format_time(self, ms: float) -> str:
        if ms < 1:
            return f"{ms * 1000:.0f}μs"
        if ms < 1000:
            return f"{ms:.1f}ms"
        return f"{ms / 1000:.2f}s"

    def render(self) -> str:
        """Render the chart as a string."""
        if not self.spans:
            return "No spans to display"

        spans = self._collapsed()
        spans_by_agent: dict[str, list[Span]] = {}
        for span in spans:
            spans_by_agent.setdefault(span.agent or "unknown", []).append(span)

        min_time = min(s.start_ms for s in spans)
        max_time = max(s.end_ms for s in spans)
        total_duration = max_time - min_time or 1

        longest = max(len(s.name) for s in spans) + 3
        label_width = max(25, min(longest, self.width // 3))
        time_width = 12
        bar_width = self.width - label_width - time_width - 4
        scale = bar_width / total_duration

        lines = self._render_header(total_duration, bar_width, label_width)
        lines.append("")

        for agent in sorted(spans_by_agent):
            agent_color = self._get_agent_color(agent)
            lines.append(f" {self._color('bold')}{agent_color}{agent}{self._reset()} ")
            for span in sorted(spans_by_agent[agent], key=lambda s: s.start_ms):
                lines.append(
                    self._render_span_line(
                        span, min_time, scale, label_width, bar_width, time_width
                    )
                )
            lines.append("")

        lines.extend(self._render_summary(total_duration, len(spans)))
        return "\n".join(lines)

    def _render_header(
        self, total_duration: float, bar_width: int, label_width: int
    ) -> list[str]:
        title_line = f"{'Agent':<{label_width}} {'Timeline':<{bar_width}} {'Duration':<12}"
        header_lines = [self._color("bold") + title_line + self._reset()]

        timeline_marks = " " * bar_width
        step = max(1, int(total_duration / 5))
        for i in range(0, int(total_duration) + step, step):
            pos = int((i / total_duration) * (bar_width - 1))
            if pos < bar_width:
                time_label = self._format_time(float(i))
                if pos + len(time_label) < bar_width:
                    timeline_marks = (
                        timeline_marks[:pos]
                        + time_label
                        + timeline_marks[pos + len(time_label) :]
                    )

        header_lines.append(
            f"{'':{label_width}} {self._color('dim')}{timeline_marks}{self._reset()}"
        )
        return header_lines

    def _render_span_line(
        self,
        span: Span,
        min_time: float,
        scale: float,
        label_width: int,
        bar_width: int,
        time_width: int,
    ) -> str:
        start_pos = int((span.start_ms - min_time) * scale)
        bar_length = max(1, int(span.duration_ms * scale))
        start_pos = max(0, min(start_pos, bar_width - 1))
        bar_length = min(bar_length, bar_width - start_pos)

        color = self._get_agent_color(span.agent, span.status)
        reset = self._reset()
        status_symbol = self.STATUS_SYMBOLS.get(span.status, "·")

        label = f"{status_symbol} {span.name}"
        if len(label) > label_width - 1:
            label = label[: label_width - 2] + "…"
        label = label.ljust(label_width)
        bar_str = " " * start_pos + color + "█" * bar_length + reset
        bar = bar_str.ljust(bar_width + len(color) + len(reset))
        time_str = self._format_time(span.duration_ms).rjust(time_width)
        return f"{label}{bar}{time_str}"

    def _render_summary(self, total_duration: float, span_count: int) -> list[str]:
        dim, reset, bold = self._color("dim"), self._reset(), self._color("bold")
        lines = [
            f"{dim}{'─' * self.width}{reset}",
            f"{bold}Summary{reset}",
            f"  • Total spans: {span_count}",
            f"  • Total duration: {self._format_time(total_duration)}",
        ]

        counts = {st: sum(1 for s in self.spans if s.status == st) for st in self.STATUS_COLORS}
        if any(counts.values()):
            ok_count = sum(1 for s in self.spans if s.status == "ok")
            parts = [f"{self._color('green')}✓ {ok_count}{reset}"]
            for status, color in self.STATUS_COLORS.items():
                if counts[status]:
                    symbol = self.STATUS_SYMBOLS[status]
                    parts.append(f"{self._color(color)}{symbol} {counts[status]}{reset}")
            lines.append(f"  • Status: {' | '.join(parts)}")
        return lines

    def print(self) -> None:
        """Print the chart to the terminal."""
        print(self.render())


class SpanCollector:
    """Collects spans for later display as a Gantt chart.

        with SpanCollector() as collector:
            collector.record_with_offset("agent_run", "growth_pm", 0, 113.9)
            with collector.span("model_call", agent="nx"):
                ...
        collector.render_gantt()
    """

    def __init__(self) -> None:
        self.spans: list[Span] = []
        self.start_time: Optional[float] = None

    def __enter__(self) -> "SpanCollector":
        self.start_time = time.time()
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def record(
        self,
        name: str,
        agent: Optional[str],
        start_time: float,
        end_time: float,
        status: str = "ok",
    ) -> None:
        """Record a span from absolute times in seconds (as in ``time.time()``)."""
        self.spans.append(
            Span(name, start_time * 1000, (end_time - start_time) * 1000, agent, status)
        )

    def record_with_offset(
        self,
        name: str,
        agent: Optional[str],
        start_offset_ms: float,
        duration_ms: float,
        status: str = "ok",
    ) -> None:
        """Record a span by ms offset from entering the ``with`` block, and its duration in ms."""
        if self.start_time is None:
            raise RuntimeError("SpanCollector must be used as a context manager")
        start = self.start_time + start_offset_ms / 1000
        self.record(name, agent, start, start + duration_ms / 1000, status)

    @contextmanager
    def span(
        self, name: str, agent: Optional[str] = None, status: str = "ok"
    ) -> Iterator[None]:
        """Time the block as a span; it is recorded as ``error`` if the block raises."""
        start = time.time()
        final_status = status
        try:
            yield
        except BaseException:
            final_status = "error"
            raise
        finally:
            self.record(name, agent, start, time.time(), final_status)

    def to_gantt(self, **gantt_kwargs: Any) -> TerminalGantt:
        """Build a ``TerminalGantt`` with times relative to the first span."""
        gantt = TerminalGantt(**gantt_kwargs)
        if self.spans:
            origin = min(s.start_ms for s in self.spans)
            for s in self.spans:
                gantt.add_span(s.name, s.start_ms - origin, s.duration_ms, s.agent, s.status)
        return gantt

    def render_gantt(self, **gantt_kwargs: Any) -> None:
        """Print the collected spans as a Gantt chart."""
        self.to_gantt(**gantt_kwargs).print()


def track_span(
    collector: SpanCollector, agent: Optional[str] = None, name: Optional[str] = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator recording each call of a sync or async function as an (indented) span.

        @track_span(collector, "growth_pm", "model_call")
        async def call_model(): ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        span_name = f"  {name or func.__name__}"

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with collector.span(span_name, agent=agent):
                    return await func(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with collector.span(span_name, agent=agent):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def create_gantt_from_pydantic_trace(result: Any) -> TerminalGantt:
    """Build a ``TerminalGantt`` from an object exposing ``spans`` (or ``_model_extra["spans"]``)."""
    gantt = TerminalGantt()

    extra = getattr(result, "_model_extra", None)
    if extra and "spans" in extra:
        gantt.add_spans_from_trace(extra)

    for span in getattr(result, "spans", []):
        gantt.add_span(
            name=getattr(span, "name", "unknown"),
            start_ms=getattr(span, "start_ms", 0),
            duration_ms=getattr(span, "duration_ms", 0),
            agent=getattr(span, "agent", None),
            status=getattr(span, "status", "ok"),
        )
    return gantt
