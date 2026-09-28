# Classification criteria

## Quick test

Ask, in order:

1. **Is there a note in the knowledge base about this?**
   No → `gap`. Stop here; do not guess at a source.
2. **Does that note record something a user actually did or said** (an
   interview, a support ticket, a usage number, a test result)?
   Yes → `evidence`.
3. **Otherwise, is it something the team wrote** (a spec, a roadmap doc, a
   stakeholder's opinion, a design rationale)?
   Yes → `assumption`.

## Examples

| Claim | Source | Kind |
| --- | --- | --- |
| "3 of 5 interviewed users abandoned signup at the payment step" | `interviews/2024-03-signup.md` | evidence |
| "Usage dropped 12% the week after the pricing change" | `analytics/pricing-change.md` | evidence |
| "We think mobile users churn faster because the layout is cramped" | `product/mobile-notes.md` (a team hypothesis, not a user report) | assumption |
| "The original spec assumed users would read the onboarding email" | `docs/onboarding-spec.md` | assumption |
| "Why do enterprise users churn in month 2?" | none | gap |

## Common mistakes

- Citing a spec as if it were evidence: a document written by the team is an
  assumption until user evidence confirms it, no matter how detailed it is.
- Marking something a gap because the note is old: stale evidence is still
  evidence (mention the staleness in the claim text, don't reclassify it).
- Giving a gap a source "just in case": a gap has no source, by definition.
