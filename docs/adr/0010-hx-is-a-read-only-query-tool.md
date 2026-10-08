# 0010. HX is a read-only query tool, and writes go through one writer

Status: accepted

## Context

HX was built as an agent the Growth PM delegated to: one caller, one
question at a time. It could also write its own working notes under
`squad/hx/**`.

The squad is moving to a committee, where several PMs form an opinion at
the same moment and each of them needs to check the knowledge base. Two
things in the old design get in the way:

- The spans of a nested HX run were collected through a single slot shared
  by every run in the squad (`sink_box`). Two runs consulting HX at once
  would overwrite each other's slot.
- Several agents writing to the same knowledge base at once, HX among
  them, can interleave writes to the same note.

There was also a boundary problem. An agent that keeps working notes
builds up a view of its own; a researcher with a view starts to argue for
it. The squad needs HX to report what the knowledge base says, not to
take part in the decision.

## Decision

- **HX is a query tool.** Roles reach it only through `consult_hx`. Each
  call is a fresh run with no message history, so one answer never leans
  on an earlier question, and any number of calls can overlap. It still
  answers with an `HXAnswer`: cited findings classified as evidence,
  assumption or gap, with every source checked against the knowledge base.
- **HX is read-only.** It loses `write_note` and its `squad/hx/**`
  permission. It keeps proposing assumption updates as findings (ADR
  0004); a role with a path to the founder carries them out.
- **HX gives no opinion on the solution.** Its role text says so, next to
  the existing rules against prioritizing and proposing features.
- **Nested runs are collected per run, not per squad.** The shared slot
  becomes a context variable (`HX_SINK`), so runs that overlap each see
  their own sink.
- **One writer.** `SerializedKnowledgeBase` wraps any `KnowledgeBase` and
  holds a lock around `write`; reads pass straight through. `ProductSquad`
  wraps the knowledge base it is given, so every write, by an agent's tool
  or by the squad itself, goes through it. The lock is a thread lock
  because the note tools are plain functions that run in worker threads.

A queue with a dedicated writer task was considered and dropped: it gives
the same ordering guarantee as the lock, and needs a running event loop
and a shutdown step that a synchronous `ProductSquad` call does not have.

## Consequences

- Breaking: HX no longer writes. Notes under `squad/hx/` stay readable,
  but nothing adds to them.
- A knowledge base passed to two `ProductSquad`s is serialized twice,
  once per squad, unless it is wrapped first and the wrapper is shared:
  `SerializedKnowledgeBase.wrap()` returns an already wrapped one
  unchanged.
- The lock orders writes inside one process. Two processes writing to the
  same vault are still not coordinated.
- Every consultation costs a model run. Nothing is cached between calls,
  on purpose: a cache would be the memory this decision removes.
- Supersedes the part of ADR 0004 that left HX a free `write` permission.
