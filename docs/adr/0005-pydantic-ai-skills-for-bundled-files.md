# 0005. Use pydantic-ai-skills for full skill support

Status: accepted

## Context

Agent Skills are a folder on disk: a `SKILL.md` (name, description,
Markdown instructions) plus optional `references/`, `assets/` and
`scripts/` files the instructions tell the agent to use. Pydantic AI
already ships a `Skills` capability, in `pydantic-ai-harness`, that reads a
library of these folders and turns each into a deferred capability the
model loads with `load_capability`. It stops there by design: it does not
enumerate, read, or execute a skill's bundled files. A `SKILL.md` that says
"see `references/FORMS.md`" or "run `scripts/aggregate.py`" hands the model
instructions it has no tool to act on.

`pydantic-ai-skills` is a separate package that requires `pydantic-ai-harness`
and adds exactly that gap: `read_skill_resource` and `run_skill_script`
tools, keyed by skill name, that reach a package's `references/`/`assets/`
files and `scripts/` — including remote registries and sandboxed execution,
neither of which this repo uses today.

## Decision

Use `pydantic-ai-skills`'s `SkillsCapability` (for discovery and the
deferred-capability catalog) and `SkillFilesToolset` (for the bundled-file
tools), isolated in `pydantic_squads.product.skills_integration`, behind a
new optional `skills` extra. `harness`'s own `Skills` is not enough on its
own: the whole point of shipping `references/` alongside each of the three
product-squad skills is that a role reads them, which `Skills` cannot do.

Within that module:

- Each role gets its own `SkillsCapability`, scoped to `role.skills` via
  `include`, so one role never sees a skill declared for another — even
  when both skills live in the same directory.
- `role.scripts` decides how `run_skill_script` behaves: `"never"` drops the
  tool, `"approval"` wraps it in `ApprovalRequiredToolset` (the same
  `DeferredToolRequests` path already used for an approval-gated note
  write), `"free"` leaves it unwrapped. `read_skill_resource` is always
  free — reading a reference file is not a side effect worth a human
  checkpoint the way running a script is.
- `pydantic_squads.product.skills_integration` is its own module, imported
  lazily and only when `ProductSquad(skills_dirs=...)` is not `None`
  (ADR 0001's pattern, one level deeper): the `ai` extra alone still works
  without the `skills` extra installed.

## Consequences

- A skill's `SKILL.md` can reference its own bundled files and have an
  agent actually reach them, not just read about their existence.
- The `skills` extra pulls in `pydantic-ai-skills` (which itself depends on
  `pydantic-ai-harness`) on top of `pydantic-ai-slim`, so a project using
  skills needs both the `ai` and `skills` extras.
- Registries, sandboxed script execution and programmatic skills are
  available from `pydantic-ai-skills` but unused here; a future need can
  reach them without changing this module's public shape.
