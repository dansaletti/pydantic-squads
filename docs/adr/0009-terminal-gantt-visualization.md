# 0009. Terminal Gantt visualization

Status: accepted

[ADR 0014](0014-request-steps-in-the-trace-and-a-live-gantt.md) adds the chart of a live
`ProductSquad` run, which this record left open.

## Context

A squad run is several overlapping agent runs, model calls and tool calls
(Growth PM, a nested HX consultation, retries). Reading that from logs or
a trace dump makes it hard to see what ran in parallel and where the time
went, and not everyone has an OTel backend at hand (ADR 0006).

## Decision

Add `pydantic_squads.visualization`, a standard-library-only module with
`TerminalGantt` (renders spans per agent with ANSI colors and
ok/retry/error status), `SpanCollector` (a context manager that times
blocks) and `track_span` (a decorator over it, sync and async).

`TerminalGantt.from_jsonl(path)` reads the `Span` lines of a trace file
(ADR 0006), indenting children under their parent. `awaiting_approval` is
a fifth known status (⏸, magenta), and `collapse_gaps_ms` shortens idle
stretches so a cycle resumed hours later stays readable.

It imports nothing outside the standard library, so exporting it from
`pydantic_squads` keeps the core free of `pydantic_ai` (ADR 0001).

## Consequences

- Timelines can be printed from any script or test without an extra.
- The agent-to-color map in `TerminalGantt.AGENT_COLORS` names the
  product squad's roles; unknown agents fall back to cyan.
- Not wired into `ProductSquad` or the `trace` CLI yet; that would be a
  separate decision. Collapsed charts show compressed, not real, time.
