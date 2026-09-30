from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

from pydantic_squads.product.observability import (
    CycleRecorder,
    SpanSink,
    deserialize_history,
    extract_spans,
    load_cycle,
    merge_nested_spans,
    serialize_history,
)

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ts(offset_seconds: float) -> datetime:
    return _BASE + timedelta(seconds=offset_seconds)


# -- extract_spans: model_call spans ---------------------------------------


def test_extract_spans_builds_one_model_call_span_for_a_plain_reply():
    """extract_spans builds a single ok model_call span for a tool-free reply"""
    messages = [
        ModelRequest(parts=[UserPromptPart("hi")], timestamp=_ts(0)),
        ModelResponse(
            parts=[TextPart("hello")],
            usage=RequestUsage(input_tokens=10, output_tokens=5),
            model_name="test-model",
            timestamp=_ts(1),
        ),
    ]
    spans = extract_spans(messages, agent="growth_pm")
    assert len(spans) == 1
    span = spans[0]
    assert span.operation == "model_call"
    assert span.agent == "growth_pm"
    assert span.status == "ok"
    assert span.input_tokens == 10
    assert span.output_tokens == 5
    assert span.duration_ms == 1000.0
    assert span.cost_usd is None
    assert span.detail is not None and span.detail.startswith("cost unavailable:")


def test_extract_spans_computes_real_cost_for_a_recognized_model():
    """extract_spans computes a real cost via genai-prices for a recognized model"""
    messages = [
        ModelResponse(
            parts=[TextPart("hello")],
            usage=RequestUsage(input_tokens=1000, output_tokens=500),
            model_name="gpt-4o",
            provider_name="openai",
            timestamp=_ts(1),
        ),
    ]
    spans = extract_spans(messages, agent="growth_pm")
    assert spans[0].cost_usd is not None
    assert spans[0].cost_usd > 0
    assert spans[0].detail is None


def test_extract_spans_returns_empty_list_for_no_messages():
    """extract_spans on an empty message list produces no spans"""
    assert extract_spans([], agent="growth_pm") == []


def test_extract_spans_output_type_is_a_no_op_with_no_model_call_spans():
    """Stamping output_type is a no-op when there is no model_call span to stamp"""
    assert extract_spans([], agent="growth_pm", output_type="Bet") == []


def test_extract_spans_stamps_output_type_onto_the_last_model_call_span():
    """extract_spans tags the run's final model_call span with the parsed output's type name"""
    messages = [ModelResponse(parts=[TextPart("ok")], model_name="test-model", timestamp=_ts(0))]
    spans = extract_spans(messages, agent="product_owner", output_type="Backlog")
    assert spans[0].output_type == "Backlog"


def test_extract_spans_uses_the_given_parent_span_id():
    """extract_spans nests every span it produces under a given parent_span_id"""
    messages = [ModelResponse(parts=[TextPart("hi")], model_name="test-model", timestamp=_ts(0))]
    spans = extract_spans(messages, agent="hx", parent_span_id="parent-1")
    assert spans[0].parent_span_id == "parent-1"


# -- extract_spans: tool_call spans -----------------------------------------


def test_extract_spans_marks_tool_span_ok_when_a_return_follows():
    """A tool call followed by a matching ToolReturnPart becomes an ok tool span"""
    messages = [
        ModelResponse(
            parts=[ToolCallPart("search_notes", {"query": "x"}, tool_call_id="call-1")],
            model_name="test-model",
            timestamp=_ts(0),
        ),
        ModelRequest(parts=[ToolReturnPart("search_notes", "[]", tool_call_id="call-1")], timestamp=_ts(1)),
    ]
    spans = extract_spans(messages, agent="growth_pm")
    model_span, tool_span = spans
    assert tool_span.operation == "tool:search_notes"
    assert tool_span.status == "ok"
    assert tool_span.parent_span_id == model_span.span_id
    assert tool_span.tool_call_id == "call-1"
    assert tool_span.duration_ms == 1000.0
    assert model_span.status == "ok"


def test_extract_spans_marks_retry_when_a_retry_prompt_follows():
    """A tool call followed by a matching RetryPromptPart marks both spans as retry"""
    messages = [
        ModelResponse(
            parts=[ToolCallPart("write_note", {}, tool_call_id="call-2")], model_name="test-model", timestamp=_ts(0)
        ),
        ModelRequest(parts=[RetryPromptPart("nope, denied", tool_call_id="call-2")], timestamp=_ts(1)),
    ]
    spans = extract_spans(messages, agent="growth_pm")
    model_span, tool_span = spans
    assert model_span.status == "retry"
    assert model_span.detail == "nope, denied"
    assert tool_span.status == "retry"
    assert tool_span.detail == "nope, denied"


def test_extract_spans_marks_awaiting_approval_when_the_run_ends_after_a_tool_call():
    """A tool call with no message after it (e.g. ApprovalRequired) is awaiting_approval"""
    messages = [
        ModelResponse(
            parts=[ToolCallPart("write_note", {}, tool_call_id="call-3")], model_name="test-model", timestamp=_ts(0)
        ),
    ]
    spans = extract_spans(messages, agent="growth_pm")
    model_span, tool_span = spans
    assert model_span.status == "awaiting_approval"
    assert tool_span.status == "awaiting_approval"
    assert tool_span.duration_ms == 0.0


def test_extract_spans_marks_error_when_no_result_matches_the_tool_call():
    """A tool call whose id matches neither a return nor a retry in the next request is an error"""
    messages = [
        ModelResponse(
            parts=[ToolCallPart("write_note", {}, tool_call_id="call-4")], model_name="test-model", timestamp=_ts(0)
        ),
        ModelRequest(
            parts=[ToolReturnPart("other_tool", "ok", tool_call_id="different-call")], timestamp=_ts(1)
        ),
    ]
    spans = extract_spans(messages, agent="growth_pm")
    tool_span = spans[1]
    assert tool_span.status == "error"
    assert tool_span.detail == "no tool result found for this call"


# -- merge_nested_spans -------------------------------------------------


def test_merge_nested_spans_splices_hx_spans_under_the_consult_hx_span():
    """merge_nested_spans attaches HX's own spans as children of the consult_hx tool span"""
    pm_messages = [
        ModelResponse(
            parts=[ToolCallPart("consult_hx", {"question": "q"}, tool_call_id="call-5")],
            model_name="test-model",
            timestamp=_ts(0),
        ),
        ModelRequest(parts=[ToolReturnPart("consult_hx", "{}", tool_call_id="call-5")], timestamp=_ts(1)),
    ]
    pm_spans = extract_spans(pm_messages, agent="growth_pm")
    consult_span = next(s for s in pm_spans if s.operation == "tool:consult_hx")
    hx_messages = [ModelResponse(parts=[TextPart("hx reply")], model_name="test-model", timestamp=_ts(2))]
    sink = SpanSink(nested_runs={"call-5": ("hx", hx_messages)})

    merged = merge_nested_spans(pm_spans, sink)

    assert len(merged) == len(pm_spans) + 1
    nested = merged[-1]
    assert nested.agent == "hx"
    assert nested.parent_span_id == consult_span.span_id


def test_merge_nested_spans_leaves_spans_unchanged_when_sink_is_empty():
    """merge_nested_spans is a no-op when the sink has no nested run for a tool span"""
    messages = [
        ModelResponse(
            parts=[ToolCallPart("consult_hx", {}, tool_call_id="call-6")], model_name="test-model", timestamp=_ts(0)
        ),
        ModelRequest(parts=[ToolReturnPart("consult_hx", "{}", tool_call_id="call-6")], timestamp=_ts(1)),
    ]
    spans = extract_spans(messages, agent="growth_pm")
    assert merge_nested_spans(spans, SpanSink()) == spans


# -- CycleRecorder / load_cycle ----------------------------------------


def test_cycle_recorder_round_trips_header_spans_and_snapshot(tmp_path):
    """A cycle's header, spans and snapshot can be read back exactly as recorded"""
    recorder = CycleRecorder(tmp_path, "cycle-1")
    recorder.start()
    recorder.start()  # a second start() on the same instance is a no-op
    spans = extract_spans(
        [ModelResponse(parts=[TextPart("hi")], model_name="test-model", timestamp=_ts(0))], agent="growth_pm"
    )
    recorder.record_spans(spans)
    recorder.record_snapshot("[]")

    header, loaded_spans, snapshot = load_cycle(tmp_path, "cycle-1")
    assert header.cycle_id == "cycle-1"
    assert len(loaded_spans) == 1
    assert snapshot.message_history_json == "[]"


def test_cycle_recorder_does_not_rewrite_header_for_an_existing_trace_file(tmp_path):
    """A fresh CycleRecorder over an already-started cycle does not duplicate the header line"""
    CycleRecorder(tmp_path, "cycle-2").start()
    path = tmp_path / "cycle-2.jsonl"
    lines_before = path.read_text().splitlines()

    CycleRecorder(tmp_path, "cycle-2").start()
    assert path.read_text().splitlines() == lines_before


def test_load_cycle_raises_when_the_trace_file_never_got_a_snapshot(tmp_path):
    """load_cycle raises if a cycle's trace file has no snapshot (e.g. a crash mid-cycle)"""
    CycleRecorder(tmp_path, "cycle-3").start()
    with pytest.raises(ValueError, match="incomplete"):
        load_cycle(tmp_path, "cycle-3")


def test_load_cycle_skips_blank_lines(tmp_path):
    """load_cycle tolerates a blank line in a trace file"""
    recorder = CycleRecorder(tmp_path, "cycle-4")
    recorder.start()
    recorder.record_snapshot("[]")
    with (tmp_path / "cycle-4.jsonl").open("a", encoding="utf-8") as f:
        f.write("\n")

    header, _spans, _snapshot = load_cycle(tmp_path, "cycle-4")
    assert header.cycle_id == "cycle-4"


# -- serialize_history / deserialize_history -----------------------------


def test_serialize_and_deserialize_history_round_trip():
    """serialize_history/deserialize_history round-trip a message list"""
    messages = [ModelRequest(parts=[UserPromptPart("hi")], timestamp=_ts(0))]
    restored = deserialize_history(serialize_history(messages))
    assert len(restored) == 1
    assert restored[0].parts[0].content == "hi"
