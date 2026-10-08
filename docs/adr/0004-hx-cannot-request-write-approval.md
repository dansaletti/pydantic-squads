# 0004. HX cannot request write approval

Status: accepted, partly superseded by [ADR 0010](0010-hx-is-a-read-only-query-tool.md)
(HX no longer has the free `squad/hx/**` write permission either)
and by [ADR 0013](0013-pm-committee-with-a-single-human-gate.md) (the role that carries out an approved write is the Facilitator)

## Context

HX runs as a nested delegate call inside the Growth PM's `consult_hx` tool —
the founder never talks to HX directly, only through `ProductSquad.chat()`.
HX's `Permissions` originally included `write_with_approval=["assumptions/**"]`,
so a `write_note` call inside HX's own run could raise `ApprovalRequired`,
producing a `DeferredToolRequests` as HX's run output.

Propagating that correctly would mean `consult_hx` surfacing a deferred
approval request up through the Growth PM's own run, through
`ProductSquad.chat()`, to the founder — plumbing a human-in-the-loop pause
through two nested agent runs, for a role the founder never addresses
directly. That's a lot of machinery for a corner case: HX proposing an
assumption status update while answering an unrelated question.

## Decision

HX's `Permissions` no longer include `write_with_approval`. HX keeps its
free `write=["squad/hx/**"]` for its own working notes, and proposes
assumption status updates as findings in its `HXAnswer` instead of writing
them. A human who wants to act on that proposal does so through the Growth
PM instead of HX: the Growth PM's `write_with_approval` gains
`"assumptions/**"` (alongside `"docs/**"`), so once the founder approves an
update in `chat()` — one level of nesting away, not two — the Growth PM can
actually write it.

## Consequences

- `hx_agent`'s `output_type` is `HXAnswer`, not `HXAnswer | DeferredToolRequests`;
  `consult_hx` no longer needs to special-case a deferred HX result, and
  the HX source validator no longer needs to pass a `DeferredToolRequests`
  through unexamined.
- The Growth PM's `Permissions.write_with_approval` includes
  `"assumptions/**"`, so it is the one role that can actually carry out an
  approved assumption update, not just talk about it.
- If a future delegate role genuinely needs to request write approval, it
  needs a way to propagate `DeferredToolRequests` through nested runs —
  that's follow-up work, not solved here.
