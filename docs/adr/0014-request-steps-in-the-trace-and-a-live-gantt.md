# 0014. A request's steps in the trace, and a Gantt from a live run

Status: accepted

## Context

A trace was a flat list of agent runs, each with its model and tool calls
under it (ADR 0006). That was enough while a cycle was one conversation and
one Product Owner run. A committee round (ADR 0013) is several runs that
belong together: a triage, opinions formed at the same time, sometimes a
rebuttal, one or two syntheses. In a flat list nothing says which runs are
one round, or that three of them overlap on purpose.

The Gantt chart (ADR 0009) could only be drawn from a trace file. A squad
built without `trace_dir` recorded no spans at all, so there was nothing to
draw from a run that had just finished.

## Decision

- **A round is one `request` span with its steps as children**: `triage`,
  `fan_out`, `synthesis`, and `rebuttal` followed by a second `synthesis`
  when the PMs diverge. Each agent run is a child of its step. `adjust()`
  adds an `adjust` step, and the human's decision a `human_decision` span,
  under the same `request`.
- **These spans belong to `"squad"`, not to a role.** `Span.agent` gains
  that value. No single agent does a fan-out, and giving the steps to the
  Facilitator would put time on its row that it did not spend.
- **A step lasts as long as the runs inside it.** Its start is its first
  run's start and its end its last run's end: derived, never timed
  separately, so a step can never disagree with what it contains.
- **Spans are kept in memory for the current cycle**, whether or not there
  is a `trace_dir`; the file gets the same spans when there is one.
  `resume()` loads them back. They are dropped when the next request
  starts.
- **`ProductSquad.gantt()` draws the current cycle from memory.** It is the
  same chart `TerminalGantt.from_jsonl` draws from the file: both go
  through `TerminalGantt.from_records`.
- **The chart draws the `squad` rows first**, as the outline of the rest,
  and every role of the product squad has a color of its own.

Wiring the Gantt into `pydantic-squads trace` stays a separate decision,
as ADR 0009 left it.

## Consequences

- The trace file format is unchanged: the new spans are ordinary `Span`
  lines, so files written before still load, and `pydantic-squads trace`
  reads the new ones without change. It no longer lists a `"squad"` span
  as slow: a step is as long as its runs by construction.
- A triage that pauses for approval and resumes is still one `triage`
  step with two runs.
- A run's span is written before its step's span. A crash in between
  leaves runs whose parent is not in the file; the readers treat a missing
  parent as a root.
- Keeping spans in memory costs one small object per model or tool call
  for the length of a request.
- An `adjust` step and the decision can fall outside the `request` bar in
  time, since the request span is closed when the round ends and the
  human decides later.
