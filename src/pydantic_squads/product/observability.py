"""Derive spans from pydantic_ai messages and persist cycles to JSONL (ADR 0006).

Needs the optional `ai` extra: alongside `assembly.py`, this is the only
other place in `pydantic_squads.product` that imports `pydantic_ai`
(ADR 0001). Kept separate from `assembly.py` so the CLI trace viewer can
depend on it without needing to build any agents.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)

from pydantic_squads.product.contracts import CycleHeader, CycleSnapshot, Span

AgentName = Literal["growth_pm", "hx", "product_owner", "designer"]


@dataclass
class SpanSink:
    """Collects a nested agent run's messages, keyed by the `tool_call_id` that triggered it.

    Threaded into `_consult_hx` the same way `ctx.usage` already is
    (ADR 0006): pydantic_ai never puts a nested run's messages into the
    outer run's `all_messages()`, so there is no way to recover HX's spans
    as children of the Growth PM's `consult_hx` span without this hook.
    """

    nested_runs: dict[str, tuple[AgentName, list[ModelMessage]]] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_span_id() -> str:
    return uuid.uuid4().hex


def _cost_usd(response: ModelResponse) -> tuple[float | None, str | None]:
    try:
        return response.cost().total_price, None
    except Exception as exc:
        return None, f"cost unavailable: {exc}"


def _retry_for(tool_call_id: str, request: ModelRequest) -> RetryPromptPart | None:
    for part in request.parts:
        if isinstance(part, RetryPromptPart) and part.tool_call_id == tool_call_id:
            return part
    return None


def _return_for(tool_call_id: str, request: ModelRequest) -> ToolReturnPart | None:
    for part in request.parts:
        if isinstance(part, ToolReturnPart) and part.tool_call_id == tool_call_id:
            return part
    return None


def _tool_span(
    call: ToolCallPart,
    response: ModelResponse,
    next_request: ModelRequest | None,
    *,
    agent: AgentName,
    parent_span_id: str,
) -> Span:
    span_id = _new_span_id()
    if next_request is None:
        # The run ended right after this tool call was made, without a
        # return or a retry ever coming back to it — e.g. it raised
        # `ApprovalRequired` and the run stopped to wait on a human.
        return Span(
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent=agent,
            operation=f"tool:{call.tool_name}",
            tool_call_id=call.tool_call_id,
            started_at=response.timestamp,
            duration_ms=0.0,
            status="awaiting_approval",
        )
    duration_ms = max((next_request.timestamp - response.timestamp).total_seconds() * 1000, 0.0)
    retry = _retry_for(call.tool_call_id, next_request)
    if retry is not None:
        return Span(
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent=agent,
            operation=f"tool:{call.tool_name}",
            tool_call_id=call.tool_call_id,
            started_at=response.timestamp,
            duration_ms=duration_ms,
            status="retry",
            detail=str(retry.content),
        )
    ret = _return_for(call.tool_call_id, next_request)
    if ret is None:
        return Span(
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent=agent,
            operation=f"tool:{call.tool_name}",
            tool_call_id=call.tool_call_id,
            started_at=response.timestamp,
            duration_ms=duration_ms,
            status="error",
            detail="no tool result found for this call",
        )
    return Span(
        span_id=span_id,
        parent_span_id=parent_span_id,
        agent=agent,
        operation=f"tool:{call.tool_name}",
        tool_call_id=call.tool_call_id,
        started_at=response.timestamp,
        duration_ms=duration_ms,
        status="ok",
    )


def extract_spans(
    messages: list[ModelMessage],
    *,
    agent: AgentName,
    parent_span_id: str | None = None,
    output_type: str | None = None,
) -> list[Span]:
    """Build spans for one agent run from its `result.all_messages()`.

    One `model_call` span per `ModelResponse`, with one `tool:<name>` child
    span per `ToolCallPart` it contains. Durations come from consecutive
    message timestamps, an approximation of true call boundaries (ADR
    0006). `output_type` is stamped onto the run's last `model_call` span,
    since the message list alone doesn't say which output type a caller
    parsed the run into.
    """
    spans: list[Span] = []
    last_model_span_index: int | None = None
    for i, message in enumerate(messages):
        if not isinstance(message, ModelResponse):
            continue
        previous = messages[i - 1] if i > 0 else None
        call_started_at = previous.timestamp if isinstance(previous, ModelRequest) else message.timestamp
        duration_ms = max((message.timestamp - call_started_at).total_seconds() * 1000, 0.0)
        next_request = messages[i + 1] if i + 1 < len(messages) else None
        if not isinstance(next_request, ModelRequest):
            next_request = None
        tool_calls = [part for part in message.parts if isinstance(part, ToolCallPart)]

        status: Literal["ok", "retry", "awaiting_approval"] = "ok"
        detail: str | None = None
        if next_request is not None:
            for call in tool_calls:
                retry = _retry_for(call.tool_call_id, next_request)
                if retry is not None:
                    status, detail = "retry", str(retry.content)
                    break
        elif tool_calls:
            status = "awaiting_approval"

        cost_usd, cost_detail = _cost_usd(message)

        model_span_id = _new_span_id()
        spans.append(
            Span(
                span_id=model_span_id,
                parent_span_id=parent_span_id,
                agent=agent,
                operation="model_call",
                started_at=call_started_at,
                duration_ms=duration_ms,
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                cost_usd=cost_usd,
                status=status,
                detail=detail or cost_detail,
            )
        )
        last_model_span_index = len(spans) - 1

        for call in tool_calls:
            spans.append(_tool_span(call, message, next_request, agent=agent, parent_span_id=model_span_id))

    if output_type is not None and last_model_span_index is not None:
        spans[last_model_span_index] = spans[last_model_span_index].model_copy(update={"output_type": output_type})

    return spans


def merge_nested_spans(spans: list[Span], sink: SpanSink) -> list[Span]:
    """Splice HX's spans in as children of each `consult_hx` tool span in `spans`."""
    merged = list(spans)
    for span in spans:
        if span.tool_call_id is None or span.tool_call_id not in sink.nested_runs:
            continue
        nested_agent, nested_messages = sink.nested_runs[span.tool_call_id]
        merged.extend(extract_spans(nested_messages, agent=nested_agent, parent_span_id=span.span_id))
    return merged


class CycleRecorder:
    """Append-only writer for one cycle's `{trace_dir}/{cycle_id}.jsonl`.

    One line per `CycleHeader` (written once), `Span` (one per recorded
    span) and `CycleSnapshot` (rewritten after every call) — so a crash
    mid-cycle still leaves the last successfully written snapshot on disk.
    """

    def __init__(self, trace_dir: Path | str, cycle_id: str) -> None:
        self.trace_dir = Path(trace_dir)
        self.cycle_id = cycle_id
        self.path = self.trace_dir / f"{cycle_id}.jsonl"
        self._header_written = self.path.exists()

    def start(self, *, schema_version: int = 1) -> None:
        """Write the cycle's header line, unless one is already on disk."""
        if self._header_written:
            return
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        header = CycleHeader(cycle_id=self.cycle_id, schema_version=schema_version, started_at=_now())
        self._append("CycleHeader", header)
        self._header_written = True

    def record_spans(self, spans: list[Span]) -> None:
        for span in spans:
            self._append("Span", span)

    def record_snapshot(self, message_history_json: str, *, schema_version: int = 1) -> None:
        snapshot = CycleSnapshot(
            cycle_id=self.cycle_id,
            schema_version=schema_version,
            message_history_json=message_history_json,
            ended_at=_now(),
        )
        self._append("CycleSnapshot", snapshot)

    def _append(self, kind: str, record: CycleHeader | Span | CycleSnapshot) -> None:
        line = json.dumps({"kind": kind, "data": json.loads(record.model_dump_json())})
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_cycle(trace_dir: Path | str, cycle_id: str) -> tuple[CycleHeader, list[Span], CycleSnapshot]:
    """Read back a cycle's header, spans and last snapshot from its trace file."""
    path = Path(trace_dir) / f"{cycle_id}.jsonl"
    header: CycleHeader | None = None
    spans: list[Span] = []
    snapshot: CycleSnapshot | None = None
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            kind, data = record["kind"], record["data"]
            if kind == "CycleHeader":
                header = CycleHeader.model_validate(data)
            elif kind == "Span":
                spans.append(Span.model_validate(data))
            elif kind == "CycleSnapshot":
                snapshot = CycleSnapshot.model_validate(data)
    if header is None or snapshot is None:
        raise ValueError(f"cycle '{cycle_id}' trace file is incomplete or missing")
    return header, spans, snapshot


def serialize_history(messages: list[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")


def deserialize_history(message_history_json: str) -> list[ModelMessage]:
    return ModelMessagesTypeAdapter.validate_json(message_history_json)
