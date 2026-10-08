# 0011. A Brief is the Product Owner's only door

Status: accepted

Since [ADR 0013](0013-pm-committee-with-a-single-human-gate.md) the committee produces the brief: `approve()` returns it, and
`close_bet()` and `Bet` are gone.

## Context

The Product Owner used to take a `Bet` straight from the Growth PM
(`submit_bet`). When the bet was too ambiguous it answered with a
`SendBack` full of questions, the Growth PM revised the bet, and
`submit_bet` returned a `Revision` for the founder to approve before
resubmitting.

Two things were wrong with that for the committee the squad is moving to:

- The human's approval was a convention. `submit_bet` took any `Bet`; the
  docstring asked callers to pass only an approved one. Nothing in the data
  said a human had decided.
- The send-back made the Product Owner a party to the discussion. With
  several PMs giving opinions, a Product Owner that asks questions back
  becomes one more voice, and its questions have no single role to go to.

## Decision

- **The Product Owner accepts one thing: a `Brief`.** It carries the
  problem, the hypothesis, the success metric, the acceptance criteria, the
  owner roles and a `HumanDecision`. `ProductSquad.submit_brief()` is the
  only method that runs the Product Owner.
- **The approval is data.** `Brief` only validates with
  `human_decision.verdict == "approved"`. `BriefDraft` is the same brief
  without the decision: what gets proposed to the human.
- **An incomplete brief is rejected by code.** `validate_brief()` returns a
  `BriefRejection` naming every missing or invalid field, and
  `submit_brief()` returns it without calling the Product Owner's model.
- **The Product Owner rejects, it does not ask.** Its output is
  `Backlog | BriefRejection`. Its role text says an unclear brief is
  rejected, not discussed.
- **Nothing is revised or resubmitted automatically.** `submit_bet`,
  `Revision` and the Growth PM's revision step are removed. Whoever owns
  the brief fixes it and submits it again.
- **Rejections show in the trace.** A code rejection records a
  `brief_validation` span; a Product Owner rejection is stamped on its
  model call. The trace CLI reports both as "Brief rejections", in place of
  "Product Owner send-backs".

Keeping `submit_bet` as an alias that builds a `Brief` from a `Bet` was
considered and dropped: it would have to invent the human decision, which
is the thing this record makes explicit.

## Consequences

- Breaking: `submit_bet`, `Revision` and the Product Owner's `SendBack` are
  gone. `SendBack` stays as the Designer's contract (ADR 0007).
- Until the committee produces briefs, `close_bet()` still returns a `Bet`
  and the caller writes the `Brief` by hand. A `Bet` has no path to the
  Product Owner.
- `owner_roles` is free text: the squad does not check it against its role
  ids, since a consuming project may name a human owner.
- Supersedes the send-back loop of ADR 0003, the `submit_bet()` revision
  note of ADR 0006, and the "Product Owner only ever sees a Bet" premise of
  ADR 0007.
