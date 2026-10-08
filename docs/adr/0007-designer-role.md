# 0007. A Designer role turns the Backlog into a prototype

Status: accepted, partly superseded by [ADR 0011](0011-brief-is-the-product-owners-only-door.md)
(the Product Owner now takes a Brief, and the trace CLI counts brief rejections)
and by [ADR 0012](0012-marketing-pm-owns-brand-and-social-media-executes.md)
(brand questions go to the Marketing PM before the founder)

## Context

The product squad stopped at a `Backlog`: stories and acceptance criteria,
but nothing a founder could click through before building. Teams were
drawing screens by hand from the backlog, reinterpreting stories on the
way and inventing a visual language per feature. There was also no design
system to keep those screens coherent.

Adding a role that produces screens raises four questions: which stories it
designs, how to know it designed all of them, where it sits in the flow,
and who decides what a designer should not (brand, tone, positioning).

## Decision

- **A fourth role, `DESIGNER`**, in `pydantic_squads.product.roles`: a
  `TASK` role that receives a `Backlog` and delivers a `Prototype` — one
  self-contained, mobile-first HTML file with several navigable screens —
  or a `SendBack`. It writes `squad/design/**` freely and
  `design-system/**` only with the founder's approval, and loads the
  `prototyping` skill. The flow is Bet → Backlog → Prototype, through
  `ProductSquad.design()`.
- **`Story.needs_design` is a required field with no default.** The Product
  Owner decides, story by story, whether it changes what a user sees or
  does. A default would let a model skip the decision silently.
- **A deterministic gate**, `design_coverage_errors(backlog, prototype)` in
  `product.contracts` (pure pydantic, ADR 0001): every story with
  `needs_design=True` appears in some `Screen`, and no `Screen` cites a
  story missing from the backlog. The Designer agent's output validator
  runs it, plus checks that the HTML exists under
  `squad/design/<cycle_id>/` and loads nothing external, and returns a
  `ModelRetry` with the specific gap. Coverage is checked by code, not
  trusted to the model.
- **The Designer runs at the top level**, like the Product Owner, not
  nested inside another agent's tool. That is what lets a
  `design-system/**` write surface as a `DeferredToolRequests` the founder
  resolves through `design(deferred_tool_results=...)` — the path ADR 0004
  says a nested role does not have. Its HX consultations are nested, as
  the Growth PM's already are, through the same `consult_hx` tool; HX still
  cannot request approval.
- **Brand, tone and positioning questions go to the founder, not to the
  Growth PM.** The Designer returns them as `FounderQuestion`s with a
  suggested default and keeps designing with that default. Asking the
  Growth PM instead would nest a conversational agent — whose answers can
  themselves need approval — inside the Designer's run, reintroducing the
  nested-approval problem of ADR 0004. HX gaps become founder questions
  too (`origin="hx_gap"`, carrying the question put to HX).
- **Founder questions are written to `squad/design/<cycle_id>/questions.md`**
  deterministically after each `Prototype`, like the Bet note (ADR 0006),
  and answered with `design(backlog, answers={question: answer})`, which
  sends the previous `Prototype` and the answers back to the Designer. An
  unanswered question keeps the suggested default.
- **No story needs design → `design()` returns `None`** without running
  the Designer. There is nothing to prototype, and an empty `Prototype`
  would be a contract with no screens.
- **A Designer `SendBack` goes to the founder**, not automatically to the
  Product Owner: the Product Owner runs without state and only ever sees a
  Bet, so it has no way to revise a Backlog it already delivered. The
  founder decides whether to resubmit the Bet or adjust the Backlog.
- **The Designer's pending approval is not checkpointed.** Its spans go to
  the cycle's trace (`Span.agent="designer"`), but its message history
  lives in memory only while a `design-system/**` write awaits approval.
  After a restart the founder calls `design()` again. `CycleSnapshot` and
  `resume()` are unchanged.

## Consequences

- `Story` gains a required field: every `Backlog` built by hand must now
  set `needs_design` on each story.
- `ProductSquad` builds a fourth agent, and `Span.agent` accepts
  `"designer"`; the trace CLI counts Designer send-backs apart from the
  Product Owner's.
- The prototype and its questions live in the knowledge base as plain
  files: `MarkdownKnowledgeBase` already writes any text path, and only
  indexes `*.md`, so the HTML never shows up in note search.
- A crash while a design-system write awaits approval loses that run; the
  cost is one extra `design()` call, not lost decisions, since approved
  writes are already in the knowledge base.
- A future need for the Product Owner to revise a Backlog from a Designer
  `SendBack` would need the Bet kept alongside it and a new revision
  contract — follow-up work, not solved here.
