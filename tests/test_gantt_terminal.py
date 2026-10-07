"""Tests for the terminal Gantt chart."""

import asyncio
from types import SimpleNamespace

import pytest

from pydantic_squads import SpanCollector, TerminalGantt, track_span
from pydantic_squads.visualization.gantt_terminal import (
    Span,
    create_gantt_from_pydantic_trace,
)


def test_span_end_is_start_plus_duration() -> None:
    """A span ends at start plus duration."""
    assert Span("a", 10, 5).end_ms == 15


def test_empty_gantt_renders_placeholder() -> None:
    """With no spans the chart renders a placeholder."""
    assert "No spans" in TerminalGantt().render()


def test_render_groups_agents_and_summarizes_statuses() -> None:
    """Spans are grouped by agent and the summary counts retries and errors."""
    g = TerminalGantt(width=100, use_colors=False)
    g.add_span("run", 0, 100, agent="nx")
    g.add_span("call", 0, 0.5, agent="nx", status="retry")
    g.add_span("boom", 50, 2000, status="error")
    g.add_span("odd", 10, 1, agent="x", status="weird")
    out = g.render()
    assert "nx" in out and "unknown" in out
    assert "⟳" in out and "✗" in out and "· odd" in out
    assert "\033" not in out
    assert "500μs" in out and "2.00s" in out


def test_render_only_ok_has_no_status_line() -> None:
    """The status line only appears when there are retries or errors."""
    g = TerminalGantt(use_colors=True)
    g.add_span("a", 5, 0)
    out = g.render()
    assert "Status:" not in out and "\033[" in out


def test_color_selection() -> None:
    """Status wins over agent color; unknown agents and no agent fall back to cyan."""
    g = TerminalGantt()
    assert g._get_agent_color("nx", "retry") == g.COLORS["yellow"]
    assert g._get_agent_color("nx", "error") == g.COLORS["red"]
    assert g._get_agent_color("NX") == g.COLORS["green"]
    assert g._get_agent_color("zzz") == g.COLORS["cyan"]
    assert g._get_agent_color(None) == g.COLORS["cyan"]
    assert TerminalGantt(use_colors=False)._color("red") == ""


def test_add_spans_from_trace() -> None:
    """Trace dicts are parsed, tolerating missing keys."""
    g = TerminalGantt()
    g.add_spans_from_trace({})
    g.add_spans_from_trace({"spans": [{"start": "1", "duration": 2}, {"name": "x", "agent": "nx"}]})
    assert [s.name for s in g.spans] == ["unknown", "x"]
    assert g.spans[0].start_ms == 1.0


def test_create_gantt_from_object() -> None:
    """Spans are read from `spans` and from `_model_extra`."""
    obj = SimpleNamespace(
        _model_extra={"spans": [{"name": "e", "start": 0, "duration": 1}]},
        spans=[SimpleNamespace(name="s", start_ms=1, duration_ms=2), SimpleNamespace()],
    )
    names = [s.name for s in create_gantt_from_pydantic_trace(obj).spans]
    assert names == ["e", "s", "unknown"]
    assert create_gantt_from_pydantic_trace(object()).spans == []
    assert create_gantt_from_pydantic_trace(SimpleNamespace(_model_extra={})).spans == []


def test_print_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """print() writes the rendered chart to stdout."""
    g = TerminalGantt(use_colors=False)
    g.add_span("a", 0, 1)
    g.print()
    assert "a" in capsys.readouterr().out


def test_collector_records_ok_and_error_spans() -> None:
    """The context manager records spans and marks raising blocks as errors."""
    c = SpanCollector()
    with c.span("fine", agent="nx"):
        pass
    with pytest.raises(ValueError):
        with c.span("bad"):
            raise ValueError
    assert [(s.name, s.status) for s in c.spans] == [("fine", "ok"), ("bad", "error")]
    assert c.spans[0].agent == "nx"
    assert len(c.to_gantt(width=80).spans) == 2
    assert c.to_gantt().spans[0].start_ms == 0


def test_collector_offsets_and_render(capsys: pytest.CaptureFixture[str]) -> None:
    """Offset records need the context manager; to_gantt makes times relative."""
    with pytest.raises(RuntimeError):
        SpanCollector().record_with_offset("a", "nx", 0, 1)
    with SpanCollector() as c:
        c.record_with_offset("run", "nx", 20, 50)
        c.record_with_offset("call", "nx", 30, 10, status="retry")
    gantt = c.to_gantt()
    assert [round(s.start_ms) for s in gantt.spans] == [0, 10]
    assert round(gantt.spans[0].duration_ms) == 50
    assert SpanCollector().to_gantt().spans == []
    c.render_gantt(use_colors=False)
    assert "run" in capsys.readouterr().out


def test_track_span_sync_and_async() -> None:
    """The decorator records sync and async calls and keeps results."""
    c = SpanCollector()

    @track_span(c, "hx")
    def add(a: int, b: int) -> int:
        return a + b

    @track_span(c, name="custom")
    async def aadd(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3
    assert asyncio.run(aadd(2, 3)) == 5
    assert [s.name for s in c.spans] == ["  add", "  custom"]
    assert add.__name__ == "add"


def test_long_labels_end_with_an_ellipsis_and_awaiting_approval_is_counted() -> None:
    """Truncated labels end in an ellipsis; awaiting approval has its own symbol and count."""
    g = TerminalGantt(width=90, use_colors=False)
    g.add_span("x" * 80, 0, 10, agent="nx", status="awaiting_approval")
    g.add_span("ok", 0, 10, agent="nx")
    out = g.render()
    assert "…" in out and "⏸ xxx" in out and "⏸ 1" in out


def test_collapse_gaps_shortens_idle_stretches_only() -> None:
    """Idle gaps longer than the limit shrink to it; overlapping spans stay put."""
    g = TerminalGantt(use_colors=False, collapse_gaps_ms=1000)
    g.add_span("a", 0, 100)
    g.add_span("b", 50, 100)
    g.add_span("c", 100_000, 100)
    g.add_span("d", 100_500, 100)
    assert [(s.start_ms, s.end_ms) for s in g._collapsed()] == [
        (0, 100),
        (50, 150),
        (1150, 1250),
        (1650, 1750),
    ]
    assert "Total duration: 1.75s" in g.render()
    assert TerminalGantt().spans == TerminalGantt()._collapsed()


def test_from_jsonl_reads_spans_and_indents_children(tmp_path) -> None:
    """A trace file becomes a chart; only Span lines count and children are indented."""
    path = tmp_path / "trace.jsonl"
    path.write_text(
        '{"kind": "CycleHeader", "data": {}}\n\n'
        '{"kind": "Span", "data": {"span_id": "a", "parent_span_id": null, "agent": "nx",'
        ' "operation": "agent_run", "started_at": "2026-10-06T20:00:00Z", "duration_ms": 10}}\n'
        '{"kind": "Span", "data": {"span_id": "b", "parent_span_id": "a", "agent": "nx",'
        ' "operation": "model_call", "started_at": "2026-10-06T20:00:01Z",'
        ' "duration_ms": 5, "status": "error"}}\n'
    )
    g = TerminalGantt.from_jsonl(path, use_colors=False)
    assert [(s.name, s.start_ms, s.status) for s in g.spans] == [
        ("agent_run", 0, "ok"),
        ("  model_call", 1000, "error"),
    ]


def test_from_jsonl_without_spans_is_empty(tmp_path) -> None:
    """A file with no Span lines gives an empty chart."""
    path = tmp_path / "t.jsonl"
    path.write_text('{"kind": "CycleHeader", "data": {}}\n')
    assert "No spans" in TerminalGantt.from_jsonl(path).render()
