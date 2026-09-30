from datetime import datetime, timezone

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")
pytest.importorskip("rich", reason="requires the 'observability' extra: uv sync --extra observability")

from pydantic_squads.cli import build_report, main, print_report
from pydantic_squads.product.contracts import Span
from pydantic_squads.product.observability import CycleRecorder

_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(**overrides) -> Span:
    defaults = dict(
        span_id="span-1",
        agent="growth_pm",
        operation="model_call",
        started_at=_TS,
        duration_ms=100.0,
        status="ok",
    )
    return Span(**{**defaults, **overrides})


def _record_cycle(trace_dir, cycle_id: str, spans: list[Span]) -> None:
    recorder = CycleRecorder(trace_dir, cycle_id)
    recorder.start()
    recorder.record_spans(spans)
    recorder.record_snapshot("[]")


def test_build_report_sums_per_agent_metrics_from_model_call_spans_only(tmp_path):
    """build_report sums duration/tokens/cost over model_call spans, excluding tool spans"""
    spans = [
        _span(span_id="s1", agent="growth_pm", input_tokens=10, output_tokens=5, cost_usd=0.01, duration_ms=200.0),
        _span(
            span_id="s2",
            agent="growth_pm",
            operation="tool:search_notes",
            parent_span_id="s1",
            tool_call_id="call-1",
            duration_ms=50.0,
        ),
        _span(span_id="s3", agent="product_owner", input_tokens=20, output_tokens=8, cost_usd=0.02, duration_ms=300.0),
    ]
    _record_cycle(tmp_path, "cycle-1", spans)

    report = build_report("cycle-1", tmp_path)

    metrics = {m.agent: m for m in report.agent_metrics}
    assert set(metrics) == {"growth_pm", "product_owner"}
    assert metrics["growth_pm"].duration_ms == 200.0
    assert metrics["growth_pm"].input_tokens == 10
    assert metrics["product_owner"].cost_usd == 0.02


def test_build_report_flags_slow_spans(tmp_path):
    """build_report flags spans whose duration exceeds the slow threshold"""
    spans = [_span(span_id="s1", duration_ms=9000.0)]
    _record_cycle(tmp_path, "cycle-2", spans)

    report = build_report("cycle-2", tmp_path, slow_threshold_ms=5000.0)

    assert [s.span_id for s in report.slow_spans] == ["s1"]


def test_build_report_flags_hx_retries_citing_a_missing_source(tmp_path):
    """build_report flags HX retries whose detail cites a missing knowledge-base source"""
    spans = [
        _span(
            span_id="s1",
            agent="hx",
            status="retry",
            detail="source 'notes/missing.md' does not exist in the knowledge base",
        ),
        _span(span_id="s2", agent="hx", status="retry", detail="some other retry reason"),
    ]
    _record_cycle(tmp_path, "cycle-3", spans)

    report = build_report("cycle-3", tmp_path)

    assert [s.span_id for s in report.hx_retries] == ["s1"]


def test_build_report_flags_product_owner_send_backs(tmp_path):
    """build_report flags Product Owner model calls whose output was a SendBack"""
    spans = [
        _span(span_id="s1", agent="product_owner", output_type="SendBack"),
        _span(span_id="s2", agent="product_owner", output_type="Backlog"),
    ]
    _record_cycle(tmp_path, "cycle-4", spans)

    report = build_report("cycle-4", tmp_path)

    assert [s.span_id for s in report.po_send_backs] == ["s1"]


def test_build_report_flags_designer_send_backs_separately(tmp_path):
    """build_report flags Designer SendBacks apart from the Product Owner's"""
    spans = [
        _span(span_id="s1", agent="designer", output_type="SendBack"),
        _span(span_id="s2", agent="designer", output_type="Prototype"),
        _span(span_id="s3", agent="product_owner", output_type="SendBack"),
    ]
    _record_cycle(tmp_path, "cycle-designer", spans)

    report = build_report("cycle-designer", tmp_path)

    assert [s.span_id for s in report.designer_send_backs] == ["s1"]
    assert [s.span_id for s in report.po_send_backs] == ["s3"]

def test_build_report_flags_pending_approvals(tmp_path):
    """build_report flags tool spans still awaiting a human approval"""
    spans = [
        _span(span_id="s1", operation="tool:write_note", tool_call_id="call-1", status="awaiting_approval"),
    ]
    _record_cycle(tmp_path, "cycle-5", spans)

    report = build_report("cycle-5", tmp_path)

    assert [s.span_id for s in report.pending_approvals] == ["s1"]


def test_build_report_excludes_approvals_already_resolved(tmp_path):
    """build_report does not flag a pending approval once a resolution span for it exists"""
    spans = [
        _span(span_id="s1", operation="tool:write_note", tool_call_id="call-1", status="awaiting_approval"),
        _span(span_id="s2", operation="approval_resolution", tool_call_id="call-1", status="ok", detail="approved"),
    ]
    _record_cycle(tmp_path, "cycle-11", spans)

    report = build_report("cycle-11", tmp_path)

    assert report.pending_approvals == []


def test_build_report_flags_cycle_and_span_budget_overruns(tmp_path):
    """build_report flags both cumulative and per-span input-token budget overruns"""
    spans = [
        _span(span_id="s1", agent="growth_pm", input_tokens=1200),
        _span(span_id="s2", agent="product_owner", input_tokens=400),
    ]
    _record_cycle(tmp_path, "cycle-6", spans)

    report = build_report("cycle-6", tmp_path, budget_tokens=1000)

    assert report.over_budget_cycle is True
    assert report.cycle_input_tokens == 1600
    assert [s.span_id for s in report.over_budget_spans] == ["s1"]


def test_build_report_skips_budget_checks_when_no_budget_given(tmp_path):
    """build_report does not flag any budget overrun when budget_tokens is None"""
    spans = [_span(span_id="s1", input_tokens=999999)]
    _record_cycle(tmp_path, "cycle-7", spans)

    report = build_report("cycle-7", tmp_path)

    assert report.over_budget_cycle is False
    assert report.over_budget_spans == []


def test_print_report_renders_the_timeline_metrics_and_diagnostics(tmp_path, capsys):
    """print_report renders the timeline, per-agent metrics and all four diagnostics"""
    spans = [
        _span(span_id="s1", agent="growth_pm", input_tokens=10, output_tokens=5, cost_usd=0.01, duration_ms=9000.0),
        _span(
            span_id="s2",
            agent="growth_pm",
            operation="tool:consult_hx",
            parent_span_id="s1",
            tool_call_id="call-1",
            duration_ms=100.0,
        ),
        _span(
            span_id="s3",
            agent="hx",
            parent_span_id="s2",
            status="retry",
            detail="source 'x.md' does not exist in the knowledge base",
        ),
        _span(span_id="s4", agent="product_owner", output_type="SendBack"),
        _span(
            span_id="s5",
            agent="growth_pm",
            status="awaiting_approval",
            operation="tool:write_note",
            tool_call_id="call-2",
        ),
    ]
    _record_cycle(tmp_path, "cycle-8", spans)
    report = build_report("cycle-8", tmp_path, budget_tokens=1)

    print_report(report)

    out = capsys.readouterr().out
    assert "cycle-8" in out
    assert "Timeline" in out
    assert "Per-agent metrics" in out
    assert "Diagnostics" in out
    assert "exceed budget" in out
    assert "Designer send-backs: 0" in out


def test_main_trace_prints_a_report_and_returns_zero(tmp_path, capsys):
    """main(['trace', cycle_id]) prints a report and returns 0"""
    _record_cycle(tmp_path, "cycle-9", [_span()])

    exit_code = main(["trace", "cycle-9", "--trace-dir", str(tmp_path)])

    assert exit_code == 0
    assert "cycle-9" in capsys.readouterr().out


def test_main_trace_for_a_missing_cycle_returns_one(tmp_path, capsys):
    """main(['trace', ...]) reports a friendly error and returns 1 for an unknown cycle_id"""
    exit_code = main(["trace", "does-not-exist", "--trace-dir", str(tmp_path)])

    assert exit_code == 1
    assert "pydantic-squads trace" in capsys.readouterr().err


def test_main_trace_reports_missing_extras_as_a_friendly_error(tmp_path, capsys, monkeypatch):
    """main(['trace', ...]) prints an install hint, not a traceback, when an extra is missing"""
    _record_cycle(tmp_path, "cycle-10", [_span()])

    def _missing_rich(report):
        raise ImportError("no module named 'rich'")

    monkeypatch.setattr("pydantic_squads.cli.print_report", _missing_rich)
    exit_code = main(["trace", "cycle-10", "--trace-dir", str(tmp_path)])

    assert exit_code == 1
    assert "pip install" in capsys.readouterr().err
