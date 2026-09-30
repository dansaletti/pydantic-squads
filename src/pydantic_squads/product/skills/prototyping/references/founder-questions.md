# Asking the founder good questions

The founder decides positioning, tone and brand, and fills the gaps HX
cannot answer. A good `FounderQuestion` takes seconds to answer.

## Shape

- **question** — one decision, answerable in a sentence. Not "What do you
  think of the design?" but "Should the primary color signal trust (blue)
  or energy (orange)?".
- **context** — at most two sentences: why this matters for these screens,
  and what HX said (or didn't).
- **suggested_default** — what you designed with in the meantime, concrete
  enough to accept as is ("Blue #1f5eff, as in the prototype").
- **origin** — `hx_gap` when HX classified it as a gap (and put the
  question you asked HX in `hx_question`); `positioning` for positioning,
  tone or brand.

## Rules

- Never block on a question: design with your suggested default and let
  the founder override it.
- Ask only what changes the design. If both answers lead to the same
  screens, don't ask.
- One decision per question; split compound questions.
- Don't ask what HX can answer — consult HX first.
- Don't ask what the backlog already settles; scope is the Product Owner's.
