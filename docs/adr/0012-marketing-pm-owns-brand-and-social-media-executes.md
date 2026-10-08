# 0012. The Marketing PM owns brand; Social Media executes under it

Status: accepted

## Context

ADR 0007 sent every positioning, tone or brand doubt the Designer had
straight to the founder, as a `FounderQuestion(origin="positioning")`. The
alternative at the time was the Growth PM, a conversational role whose
answers can themselves need approval; nesting it inside the Designer's run
would have brought back the nested-approval problem of ADR 0004.

That left two gaps:

- The founder was asked things the knowledge base already answers. A
  positioning note written last month still produced a question, because
  nobody in the squad was responsible for reading it.
- The Growth PM carried the marketing skills (positioning, psychology,
  launch, social) next to funnel and experiment skills. One role giving
  both the growth view and the brand view is one opinion, not two.

The squad is also moving to a committee of PMs (ADR 0010, ADR 0011), and a
committee needs the marketing view to be a role of its own.

## Decision

- **A Marketing PM (`pm_marketing`) owns positioning, branding, naming and
  messaging.** It is a task role and a member of the committee: it gives an
  `Opinion` like the Growth PM and the Product PM. It takes
  `product-marketing`, `marketing-psychology` and `launch` from the Growth
  PM.
- **It also answers brand questions as a query tool.** A role that declares
  `consult_pm_marketing` gets a `MarketingGuidance` back: `answered=True`
  with the answer and the notes it comes from, or `answered=False` saying
  what the knowledge base lacks. Each call is a fresh run that only reads
  notes. It never writes, so it never needs approval, which is what made
  the Growth PM unusable here. It does not consult HX in this mode, so a
  consultation is never nested two levels deep.
- **The Designer asks the Marketing PM before the founder.** A
  `FounderQuestion(origin="positioning")` must carry `marketing_question`,
  the question put to the Marketing PM, and the prototype gate refuses it
  unless that exact question came back unanswered in the same design run.
  A revision round (`design(answers=...)`) may carry over the brand
  questions the previous prototype left open.
- **The Designer no longer lists the Product Owner in `talks_to`.** Its
  `SendBack` already went to the founder (ADR 0007); the edge was never
  used.
- **Social Media (`social_media`) is an execution role under the Marketing
  PM**, like the Designer under the Product Owner: a task role outside the
  committee. `ProductSquad.produce_content(brief)` takes an approved
  `Brief`, and the role writes landing-page copy and posts under
  `squad/content/<cycle_id>/` and returns a `ContentPack`. A gate checks
  that every piece listed is a file that exists under that folder. It
  takes the `social` skill, consults the Marketing PM on brand, and
  publishes nothing.

Letting the Marketing PM decide a brand question the knowledge base does
not settle was considered and dropped: it would be a model inventing a
brand. Those questions still go to the human.

## Consequences

- Breaking: a positioning `FounderQuestion` built by hand now needs
  `marketing_question`. The Growth PM loses four skills.
- `build_product_squad()` has seven roles, and `Span.agent` accepts
  `"pm_marketing"` and `"social_media"`.
- Every brand doubt costs a model run, as every HX consultation does.
- The match between `marketing_question` and the question asked is exact.
  A Designer that rephrases it is sent back with the list of questions
  left unanswered.
- `product-marketing` used to end by writing `docs/product-marketing.md`.
  The Marketing PM cannot write, so the skill now hands the draft over
  when the role running it has no `write_note`.
- A `ContentPack` is content in the knowledge base. Reviewing and
  publishing it is the human's job.
- Supersedes the part of ADR 0007 that sent brand questions straight to
  the founder.
