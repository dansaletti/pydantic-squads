# Roadmap

Non-binding. Features are promoted to the core only when a real squad needs
them. The reference squad is `pydantic_squads.product` (see ADR 0003); the
items below are being built through it, in phases:

1. **Hand-off contracts**: typed Pydantic models for what flows between
   roles — `pydantic_squads.product.contracts` (`Finding`, `HXAnswer`,
   `Triage`, `Opinion`, `Synthesis`, `Brief`, `Backlog`, `BriefRejection`,
   `SendBack`, `MarketingGuidance`, `ContentPack`).
2. **Knowledge base**: a protocol for reading and writing notes, with a
   markdown/Obsidian adapter, path containment and no delete operation —
   `pydantic_squads.product.knowledge`.
3. **Assembly**: build Pydantic AI `Agent`s from the product roles,
   contracts and knowledge-base tools, behind the optional `ai` extra —
   `pydantic_squads.product.assembly`.
4. **Flow helpers**: `submit_brief()` is the Product Owner's only door: it
   takes a `Brief` a human approved and rejects anything else before the
   model runs (see ADR 0011). The brief comes from the committee (item 10).
5. **Skills**: per-role Agent Skills (`SKILL.md` plus `references/`,
   `assets/` and `scripts/`), behind the optional `skills` extra —
   `pydantic_squads.product.skills_integration` (see ADR 0005).
6. **Designer**: a fourth role that turns the stories that need design into
   a self-contained, mobile-first HTML prototype and grows the product's
   design system, with a deterministic coverage gate and founder questions
   — `ProductSquad.design()` (see ADR 0007).
7. **Observability and checkpointing**: spans, cost and tokens per cycle,
   persisted snapshots to resume a conversation, an optional OpenTelemetry
   export and the `pydantic-squads trace` command —
   `pydantic_squads.product.observability`, `.otel` and `pydantic_squads.cli`
   (see ADR 0006).
8. **Claude Code backend**: run the squad on a local Claude Code login
   instead of an API key, keeping the squad's tools, approvals and
   validators in Pydantic AI — `pydantic_squads.product.claude_code` (see
   ADR 0008).
9. **Terminal Gantt**: a standard-library chart of a run's spans per agent,
   readable from a trace file — `pydantic_squads.visualization`,
   `TerminalGantt.from_jsonl` (see ADR 0009).

10. **PM committee**: a neutral Facilitator as the only conversational
    role, a committee of PMs (Growth, Product, Marketing) giving opinions
    in parallel, a synthesis that keeps their disagreements and the gaps
    HX reported, and one human gate (`approve`/`adjust`/`reject`) in front
    of the Product Owner — `ProductSquad.close_request()`/`review()` and
    `pydantic_squads.product.committee` (see ADRs 0010 to 0013).

11. **Gantt of a live run**: a committee round is traced as one request
    with its steps (triage, fan-out, rebuttal, synthesis), and
    `ProductSquad.gantt()` draws the current cycle from memory, with or
    without a trace file (see ADR 0014).

12. **Terminal session**: `pydantic-squads chat VAULT` runs the whole flow
    with no code to write, on the recommended Claude Code setup by default
    — `pydantic_squads.product.chat` (see ADR 0017).

## Next

Open, with no commitment:

- Wire the Gantt into `pydantic-squads trace` (ADR 0009 left it as a
  separate decision).
