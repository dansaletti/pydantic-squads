# 0016. Shared HX evidence, brief outputs, and a model per role

Status: accepted

## Context

After search started returning excerpts (ADR 0015), a request on a real
vault cost about 55% less. A second measured run showed where the rest
was:

- **HX was 46% of the cost**, and the PMs asked it overlapping questions.
  Three of the four gaps in the synthesis had been reached by two or three
  PMs, each through a consultation of its own. The Facilitator had already
  consulted HX during the conversation, and the PMs never saw that answer.
- **Output was 45% of the cost.** The Facilitator's replies in the
  conversation ran from 1,200 to 3,000 tokens, an HX answer reached 5,000,
  and a PM's reply to a divergence restated its whole opinion.
- **Every role ran on one model.** The roles do different work: HX
  retrieves and classifies, the PMs judge, the Facilitator and the Product
  Owner organize. `ProductSquad` took a single `model`.

## Decision

- **The PMs start from what HX already answered.** Every HX answer the
  Facilitator got in the request, in the conversation or the triage, goes
  into each PM's opinion prompt, with its question, findings and sources.
  The PMs are told to consult HX only for what those answers leave open.
  It is evidence, not opinion: the PMs still do not see each other. Gaps in
  those answers count in the synthesis as asked by the Facilitator.
- **Prompts and roles ask for brevity.** The Facilitator keeps conversation
  turns to a few lines and two or three questions. HX gives one sentence
  per finding. An opinion is one short paragraph with at most five risks
  and three questions. A reply to a divergence says only what the PM keeps
  or changes. The synthesis does not repeat the opinions the runtime
  already attaches. These are instructions, not length limits in the
  contracts: a limit would turn a long answer into a retry, which costs
  more than it saves.
- **`ProductSquad(models={role_id: model})` runs a role on its own model.**
  A role not named uses `model`. The Facilitator's three agents
  (conversation, triage, synthesis) share the Facilitator's model, and the
  Marketing PM's two (opinion, guidance) share its own. An id that is no
  role of the squad is an error.
- **On the Claude Code backend a model can carry a reasoning effort.**
  `"claude-code:<model>:<effort>"` passes `--effort` to the CLI (`low` to
  `max`), so a role can think longer on the same model:
  `models={"pm_product": "claude-code:sonnet:high"}`. The trace shows the
  model as `sonnet:high`.

The library sets no default per role: which model suits which role depends
on the provider and on the consuming project's budget. It does ship one
tested setup for Claude Code as a preset, `RECOMMENDED_MODEL` and
`RECOMMENDED_ROLE_MODELS` in `product.claude_code`: the PMs on Sonnet with
extended thinking, HX on Haiku, the rest on Sonnet. On the vault of the
measured runs that setup, with everything else in this record and in ADR
0015, took a request from an estimated US$ 4.74 to US$ 0.64. A caller opts
into it; `pydantic-squads chat` (ADR 0017) does by default. Making the rebuttal
optional was considered and left out: it removes something the human sees
at the gate.

## Consequences

- A PM may consult HX less, or not at all, when the Facilitator's
  consultation covered its question. If the Facilitator did not consult
  HX, nothing is shared and the round is as before.
- A PM can cite a note it knows only through an HX finding. The source
  still has to exist.
- Shared answers are kept for the current request only and are not
  restored by `resume()`.
- Brevity is the model's to follow. The opinions are shorter by
  instruction, so their depth has to be judged on real runs.
- A cheaper model for HX is the largest single saving and the largest risk
  to quality: a small model follows the tool protocol less reliably
  (ADR 0008). A stronger model for the PMs costs more per call. Both are
  the caller's choice.
- With roles on different models, a trace has to say which model answered:
  a `model_call` span carries `model`, and `pydantic-squads trace` lists
  each agent's models, calls and retries. Traces written before this have
  no model on their spans.
- Not a breaking change: `models` is optional and prompts are not public
  API.
