import sys
from datetime import datetime, timezone

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")
pytest.importorskip("rich", reason="requires the 'observability' extra: uv sync --extra observability")

from pydantic_squads.cli import build_report, main, print_report, role_models
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


def test_build_report_lists_the_models_calls_and_retries_of_each_agent(tmp_path):
    """Per-agent metrics say which models answered, how many calls there were and how many were retried"""
    spans = [
        _span(span_id="s1", agent="hx", model="haiku"),
        _span(span_id="s2", agent="hx", model="haiku", status="retry"),
        _span(span_id="s3", agent="hx", model="sonnet"),
        _span(span_id="s4", agent="growth_pm"),  # a trace written before spans had a model
    ]
    _record_cycle(tmp_path, "cycle-models", spans)

    report = build_report("cycle-models", tmp_path)

    by_agent = {m.agent: m for m in report.agent_metrics}
    assert (by_agent["hx"].models, by_agent["hx"].calls, by_agent["hx"].retried) == (["haiku", "sonnet"], 3, 1)
    assert (by_agent["growth_pm"].models, by_agent["growth_pm"].calls) == ([], 1)


def test_build_report_does_not_call_a_request_step_slow(tmp_path):
    """A "squad" span is a whole step of a request: it is never listed as a slow span"""
    spans = [
        _span(span_id="s1", agent="squad", operation="fan_out", duration_ms=60000.0),
        _span(span_id="s2", agent="pm_product", operation="agent_run", duration_ms=60000.0),
    ]
    _record_cycle(tmp_path, "cycle-steps", spans)

    report = build_report("cycle-steps", tmp_path, slow_threshold_ms=5000.0)

    assert [s.span_id for s in report.slow_spans] == ["s2"]


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


def test_build_report_flags_brief_rejections(tmp_path):
    """build_report flags the spans whose output was a BriefRejection"""
    spans = [
        _span(span_id="s1", agent="product_owner", output_type="BriefRejection"),
        _span(span_id="s2", agent="product_owner", output_type="Backlog"),
    ]
    _record_cycle(tmp_path, "cycle-4", spans)

    report = build_report("cycle-4", tmp_path)

    assert [s.span_id for s in report.brief_rejections] == ["s1"]


def test_build_report_flags_designer_send_backs_separately(tmp_path):
    """build_report flags Designer SendBacks apart from brief rejections"""
    spans = [
        _span(span_id="s1", agent="designer", output_type="SendBack"),
        _span(span_id="s2", agent="designer", output_type="Prototype"),
        _span(span_id="s3", agent="product_owner", output_type="BriefRejection"),
    ]
    _record_cycle(tmp_path, "cycle-designer", spans)

    report = build_report("cycle-designer", tmp_path)

    assert [s.span_id for s in report.designer_send_backs] == ["s1"]
    assert [s.span_id for s in report.brief_rejections] == ["s3"]

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
        _span(span_id="s4", agent="product_owner", output_type="BriefRejection"),
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
    assert "Brief rejections: 1" in out
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


# -- pydantic-squads chat (ADR 0017) -----------------------------------------


def test_role_models_layers_base_shorthands_and_pairs():
    """role_models starts from the base, applies the PM and HX shorthands, and lets a ROLE=MODEL pair win"""
    committee = ("growth_pm", "pm_product")
    assert role_models(None, None, [], committee) == {}
    assert role_models("opus", "haiku", ["growth_pm = sonnet"], committee, {"designer": "base"}) == {
        "designer": "base",
        "growth_pm": "sonnet",
        "pm_product": "opus",
        "hx": "haiku",
    }


def _chat_without_input(monkeypatch):
    """Make the session's prompt hit the end of input at once, as an empty stdin would."""

    def no_input(self, *args, **kwargs):
        raise EOFError

    monkeypatch.setattr("rich.console.Console.input", no_input)


def test_main_chat_runs_a_session_on_the_given_model(tmp_path, capsys, monkeypatch):
    """main(['chat', vault, --model ...]) builds the squad on that model for every role and runs the session"""
    _chat_without_input(monkeypatch)
    context = tmp_path / "product.md"
    context.write_text("A B2B tool")
    exit_code = main(["chat", str(tmp_path), "--model", "test", "--context", str(context), "--request-limit", "5"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Model: test\n" in out and "Nothing has run yet." in out


def test_main_chat_defaults_to_the_recommended_setup(tmp_path, capsys, monkeypatch):
    """With no --model, chat uses the recommended Claude Code models, and options adjust single roles"""
    _chat_without_input(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude")
    exit_code = main(["chat", str(tmp_path), "--hx-model", "claude-code:sonnet", "--skills"])
    out = " ".join(capsys.readouterr().out.split())
    assert exit_code == 0
    assert "Model: claude-code:sonnet (except growth_pm on claude-code:sonnet:high" in out
    assert "hx on claude-code:sonnet)" in out


def test_main_chat_takes_extra_skill_folders(tmp_path, capsys, monkeypatch):
    """--skills-dir turns skills on with that folder added"""
    _chat_without_input(monkeypatch)
    exit_code = main(["chat", str(tmp_path), "--model", "test", "--skills-dir", str(tmp_path)])
    assert exit_code == 0


def test_main_chat_needs_a_vault_folder(tmp_path, capsys):
    """chat on a path that is not a folder reports it and returns 1"""
    exit_code = main(["chat", str(tmp_path / "missing"), "--model", "test"])
    assert exit_code == 1
    assert "is not a folder of notes" in capsys.readouterr().err


def test_main_chat_needs_claude_code_for_a_claude_code_model(tmp_path, capsys, monkeypatch):
    """chat with a claude-code model and no `claude` on the PATH says how to fix it and returns 1"""
    monkeypatch.setattr("shutil.which", lambda name: None)
    exit_code = main(["chat", str(tmp_path)])
    assert exit_code == 1
    assert "Claude Code was not found" in capsys.readouterr().err


def test_main_chat_rejects_a_model_for_an_unknown_role(tmp_path, capsys):
    """--role-model naming a role the squad does not have reports it and returns 1"""
    exit_code = main(["chat", str(tmp_path), "--model", "test", "--role-model", "orchestrator=test"])
    assert exit_code == 1
    assert "orchestrator" in capsys.readouterr().err


def test_main_chat_reports_missing_extras_as_a_friendly_error(tmp_path, capsys, monkeypatch):
    """chat prints an install hint, not a traceback, when an extra is missing"""
    monkeypatch.setitem(sys.modules, "pydantic_squads.product.chat", None)
    exit_code = main(["chat", str(tmp_path), "--model", "test"])
    assert exit_code == 1
    assert "pydantic-squads[ai,observability]" in capsys.readouterr().err


def _skills_config_file(tmp_path, body: str = "skills:\n  rules:\n    designer: [Read MASTER.md first.]\n"):
    config = tmp_path / "squads.yaml"
    config.write_text(body)
    return str(config)


def test_main_chat_takes_a_skills_config(tmp_path, capsys, monkeypatch):
    """--config hands the file's skills section to the squad"""
    pytest.importorskip("pydantic_ai_skills", reason="requires the 'skills' extra: uv sync --extra skills")
    _chat_without_input(monkeypatch)
    assert main(["chat", str(tmp_path), "--model", "test", "--config", _skills_config_file(tmp_path)]) == 0


def test_main_chat_reports_a_skills_config_it_cannot_use(tmp_path, capsys):
    """A config that is missing, or names a role the squad does not have, is reported and returns 1"""
    pytest.importorskip("pydantic_ai_skills", reason="requires the 'skills' extra: uv sync --extra skills")
    assert main(["chat", str(tmp_path), "--model", "test", "--config", str(tmp_path / "missing.yaml")]) == 1
    assert "missing.yaml" in capsys.readouterr().err
    config = _skills_config_file(tmp_path, "skills:\n  rules:\n    orchestrator: [x]\n")
    assert main(["chat", str(tmp_path), "--model", "test", "--config", config]) == 1
    assert "orchestrator" in capsys.readouterr().err


def test_main_chat_config_reports_a_missing_skills_extra(tmp_path, capsys, monkeypatch):
    """--config without the skills extra prints an install hint, not a traceback"""
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert main(["chat", str(tmp_path), "--model", "test", "--config", _skills_config_file(tmp_path)]) == 1
    assert "uv sync --extra skills" in capsys.readouterr().err


def test_main_skills_install_clones_and_reports_the_license(tmp_path, capsys, monkeypatch):
    """skills install clones the repository into --dir and prints where it landed and its license"""

    def fake_git(command, **kwargs):
        target = tmp_path / "pm-skills"
        target.mkdir()
        (target / "LICENSE").write_text("MIT License\n")

    monkeypatch.setattr("subprocess.run", fake_git)
    assert main(["skills", "install", "phuryn/pm-skills", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"Installed in {tmp_path / 'pm-skills'}" in out and "License: MIT License" in out


def test_main_skills_install_reports_a_repository_it_cannot_install(tmp_path, capsys):
    """skills install on something that is not a repository reports it and returns 1"""
    assert main(["skills", "install", "not a repo", "--dir", str(tmp_path)]) == 1
    assert "is not a GitHub owner/name" in capsys.readouterr().err
