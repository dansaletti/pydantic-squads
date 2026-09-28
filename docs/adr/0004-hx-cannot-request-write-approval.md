# 0004. HX cannot request write approval

Status: accepted

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
PM — whose `write_with_approval=["docs/**"]` is already reachable from
`chat()`, one level of nesting away from the founder — not through HX.

## Consequences

- `hx_agent`'s `output_type` is `HXAnswer`, not `HXAnswer | DeferredToolRequests`;
  `consult_hx` no longer needs to special-case a deferred HX result, and
  the HX source validator no longer needs to pass a `DeferredToolRequests`
  through unexamined.
- If a future delegate role genuinely needs to request write approval, it
  needs a way to propagate `DeferredToolRequests` through nested runs —
  that's follow-up work, not solved here.
