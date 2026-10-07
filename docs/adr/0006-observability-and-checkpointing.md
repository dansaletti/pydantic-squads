# 0006. Observability and checkpointing for the product squad

Status: accepted

## Context

`ProductSquad` runs the Growth PM, HX and Product Owner through nested
Pydantic AI agent calls, but nothing about a run survives past
`ProductSquad._history` in memory: no record of cost, tokens, timing,
retries or approvals; no way to resume a conversation after a process
restart; no visibility into the nested `consult_hx` call, where HX runs
*inside* the Growth PM's tool and its messages never appear in the Growth
PM's own `result.all_messages()`.

Founders and teams using the product squad need to see what a cycle
(conversation → Bet → Backlog) actually cost, diagnose slow or failing
steps, and pick a conversation back up later — without the library reaching
into pydantic_ai internals from core, and without silently sending
conversation content anywhere by default.

## Decision

- **Span and cycle data models are pure pydantic**, added to
  `product.contracts` (`Span`, `CycleHeader`, `CycleSnapshot`, `BetRecord`),
  so they stay readable and testable without `pydantic_ai` installed
  (ADR 0001). Only the code that *derives* them from `ModelMessage`,
  `RunUsage` and `ModelResponse.cost()` — `product.observability` — sits
  behind the `ai` extra.
- **Spans are derived post-hoc from each call's `result.new_messages()`**
  (not `all_messages()`), not by wrapping every model/tool call
  individually. `new_messages()` — only the messages this specific call
  added — matters because `ProductSquad` keeps growing one cumulative
  `message_history`: extracting from `all_messages()` on every call would
  re-record every prior turn's spans again each time. This is cheap and
  non-invasive, at the cost of timestamp precision: message timestamps mark
  when a request was built or a response received, not exact call
  boundaries. Each `ProductSquad` call additionally records one wall-clock
  `agent_run` span around the whole `run_sync`, so the top-level duration
  per call is exact even though the spans nested under it are approximate.
  A tool call left `awaiting_approval` gets no further span on the turn
  that deferred it — the next call, resuming with `deferred_tool_results`,
  can't see that original tool call in its own `new_messages()` either, so
  it instead records a small `approval_resolution` span (keyed by
  `tool_call_id`, status `ok`/`error` for approved/denied) alongside
  whatever else that turn does.
- **HX's nested run is attributed via an explicit `SpanSink`**, threaded
  into `_consult_hx` the same way `ctx.usage` already is. There is no way
  to recover a nested run's messages from the outer run's
  `all_messages()` — pydantic_ai simply doesn't put them there — so making
  HX's spans appear as children of the Growth PM's `consult_hx` span
  requires this one, explicit, additive hook.
- **Persistence is one append-only JSONL file per cycle**
  (`{trace_dir}/{cycle_id}.jsonl`: a header line, one line per span, and a
  rolling snapshot line rewritten after every call). This is what makes
  `resume(cycle_id)` and the CLI trace viewer possible without a database
  dependency, and it degrades safely — a crash mid-cycle still leaves the
  last successfully written snapshot on disk.
- **Bet notes are written deterministically**, not left to the model to
  remember via `write_note`: `close_bet()` and a revision inside
  `submit_bet()` write a `BetRecord` (with `cycle_id`, `schema_version`,
  `bet_version_id`, `previous_bet_version_id`) to `squad/bets/**` using a
  new `format_note()` frontmatter serializer in `product.knowledge`. `Bet`
  itself, the Growth PM's LLM output schema, is untouched — bookkeeping ids
  never become something the model has to fill in.
- **The local trace viewer (`pydantic-squads trace`, built on `rich`) is
  the default observability surface**, and lives behind its own
  `observability` extra. Export to an OpenTelemetry/Logfire backend
  (`product.otel.enable_otel()`) is a **fully separate, off-by-default**
  `otel` extra: it is one-way telemetry, not a state store, so it never
  substitutes for the JSONL/resume mechanism, and it must be turned on
  explicitly because it sends full conversation content — including
  knowledge-base note contents — off the local machine.

## Consequences

- Two new optional extras (`observability` for the CLI, `otel` for
  telemetry export), on top of the existing `ai` and `skills`.
- `_consult_hx`/`_register_consult_hx` gain an additive `SpanSink`
  parameter; every existing direct call to `_consult_hx` in tests keeps
  working unchanged.
- `close_bet()`/`submit_bet()` gain a real side effect (writing a Bet note)
  that did not exist before; `GROWTH_PM.permissions.write` already covers
  `squad/bets/**`, so no permission change is needed.
- Trace files can contain full conversation content on disk; `trace_dir` is
  opt-in and `None` by default, and the README documents this alongside the
  OTel warning.
- Span timestamps are bounded by what pydantic_ai exposes in
  `all_messages()`, not true wall-clock instrumentation around every model
  and tool call — acceptable for a bar-chart-level trace viewer, not for
  precise latency SLOs.
- Cost figures degrade to `None` (with a `detail` note) for a model
  `genai-prices` doesn't recognize, rather than failing the cycle. A
  backend that prices its own calls (Claude Code, ADR 0008) puts the cost
  on the response's usage, and that figure is used as is.
