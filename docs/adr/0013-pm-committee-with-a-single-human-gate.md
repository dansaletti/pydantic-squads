# 0013. A committee of PMs behind a neutral Facilitator, with one human gate

Status: accepted

## Context

The squad was "the founder talks to the Growth PM". One role held the
conversation, formed the only product opinion (a `Bet`), and was the path
to the Product Owner. That made three things hard:

- There was one view. Growth, product and marketing concerns reached the
  human already merged by a single model, with no way to see where they
  pulled apart.
- The role that ran the conversation also had a stake in its outcome. A
  conversational agent that holds an opinion steers the conversation
  toward it.
- The human decided in pieces: reading a bet, then a revision, with the
  approval living outside the data (ADR 0011 fixed the last part).

ADR 0010 made HX safe to consult in parallel, ADR 0011 made the `Brief`
the Product Owner's only input, and ADR 0012 split marketing into its own
PM. This record puts them together.

## Decision

- **The only conversational role is a neutral Facilitator.** `chat()`
  talks to it. It makes the request clear and may consult HX. Giving an
  opinion, recommending a solution and taking a side are out of its scope.
  The Growth PM becomes a task role like the Product PM and the Marketing
  PM. The default policies are unchanged and still hold, with the
  Facilitator as the single conversational role.
- **Neutrality is held by code where it can be.** The Facilitator's
  conversational agent has no tool that reaches a PM. The agent that
  writes the synthesis has no tool at all. `Synthesis` has no field for a
  recommendation of the Facilitator's own. The Facilitator has no PM
  skills.
- **Closing the conversation is a triage, not an opinion.**
  `close_request()` produces a `Triage`: the request restated, the PMs to
  hear, and why. `review(request)` does the same for a request given
  directly. A triage can only name PMs of the committee.
- **The PMs give opinions in parallel and in isolation.** Each runs with
  no message history and without seeing the others, consulting HX on its
  own. The role on an `Opinion` is stamped by the runtime and its sources
  must be notes that exist. PMs do not list each other in `talks_to`.
- **At most one rebuttal.** When the first synthesis lists divergences,
  the PMs cited in them reply once, seeing the positions, and the
  synthesis is redone. What still diverges stays in the synthesis. The
  code has no loop: a second rebuttal cannot happen.
- **The synthesis does not force a consensus.** It lists each divergence
  with every PM's position, and a position can only be attributed to a PM
  that gave an opinion. The runtime attaches the original opinions whole,
  the replies, and the gaps, so the human always has the raw material next
  to the summary.
- **What the squad does not know is part of the synthesis.** Every gap HX
  reported to a PM during the round is listed with the questions that
  surfaced it and the PMs that asked. HX answers carry the caller's
  question word for word for this.
- **The Facilitator groups the gaps; code keeps every one of them.** HX
  rewords the same gap on each consultation, so a list matched on wording
  repeats itself: the first real run listed nine gaps, four of them "there
  is no user evidence". The Facilitator now says which gaps are the same
  thing, by number, with one sentence per group. `group_gaps` builds the
  list from that and holds it to the raw one: a gap put in two groups
  stays in the first, a gap left out becomes a group of its own in HX's
  words, and each group's questions and PMs are joined by code. Grouping
  can shorten the list but cannot lose a gap. The raw list stays in
  `Synthesis.raw_gaps` and in the note, as the opinions do.
- **The human decides once per request.** `approve()` stamps a
  `HumanDecision` on the proposed brief and returns the `Brief`, without a
  model call. `adjust(notes)` redoes only the synthesis, from the same
  opinions, and returns to the same gate. `reject(reason)` ends the
  request with no brief. After a decision the next `chat()` or `review()`
  starts a new request with a new `cycle_id`; `submit_brief()`,
  `produce_content()` and `design()` called before that stay in the
  decided request's cycle.
- **The Product Owner's single door is a validated rule.**
  `product_owner_has_one_door` is a policy of the product squad: no role
  but the Facilitator lists `product_owner` in `talks_to`.
- **Everything the human saw is kept.** Each synthesis is written to
  `squad/committee/<cycle_id>/synthesis-<n>.md`, the decision to
  `decision.md` next to it, and an approved brief to
  `squad/briefs/<brief_id>.md`. These are written by the squad, not by an
  agent's tool: the Facilitator cannot write a brief.

A separate `ProductCommittee` class was considered and dropped: `chat()`
and the closing of the conversation are already the committee's entry, so
it would have been a second object holding the same state. A detection
step separate from the synthesis was also dropped: it costs a model call
on every request, where synthesizing first costs one only when the PMs
agree.

## Consequences

- Breaking: `Bet`, `BetRecord` and `close_bet()` are gone, with no alias.
  `close_request()` returns a `Synthesis`. The README carries a migration
  table. A `Bet` was a PM's opinion (hypothesis, metric, scope); a neutral
  Facilitator cannot write one.
- The human talks to the squad at two moments: the conversation that
  clarifies the request, and the gate. The decision is still one per
  request.
- A request with three PMs costs a triage, three opinions each with its
  HX consultations, and one synthesis; two more runs per cited PM and one
  more synthesis when they diverge. `usage_limits` still caps every run.
- A synthesis waiting at the gate lives in memory. `resume()` restores the
  Facilitator's conversation only; after a restart, `close_request()` runs
  the round again. The notes of the earlier round stay in the knowledge
  base.
- Triage runs on its own agent, with the Facilitator's role, tools and
  conversation: pydantic_ai does not allow a per-run output type on an
  agent that has output validators.
- Which gaps are "the same" is a model's call, and the sentence naming a
  group is the Facilitator's. That is why HX's own wording is kept next to
  it.
- Supersedes the role list of ADR 0003, the Growth PM as the approval path
  in ADR 0004 (it is the Facilitator), and the Bet note and Growth PM
  snapshot of ADR 0006 (a brief note, and the Facilitator's conversation).
