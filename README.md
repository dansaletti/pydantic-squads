# pydantic-squads

[Português](README.pt-BR.md)

Declarative, validated agent squads on top of [Pydantic AI](https://ai.pydantic.dev).

> Early stage (pre-alpha). The API will change. Not affiliated with the Pydantic team.

Most multi-agent frameworks focus on how agents *run*. `pydantic-squads` focuses on how a squad is *defined*: who each agent is, what it must not do, who it talks to, what it may write, and what it hands off to whom. Definitions are plain Pydantic models, so they are validated at construction time and testable without calling an LLM.

## Concepts

- **Role**: an agent's mission, responsibilities, out-of-scope items, principles, interaction mode, who it talks to, tools and permissions. Its system instructions are rendered from this data, so there is a single source of truth.
- **Interaction modes**: `conversational` (talks to the human), `delegate` (called by another agent as a tool), `task` (receives a contract, delivers a contract).
- **Squad**: a composition of roles, validated on creation.
  - **Invariants** hold for every squad: unique ids, no references to unknown roles, `human` is reserved, and there is no delete permission.
  - **Policies** are opinionated and swappable. The defaults: exactly one conversational role, and only it talks to the human.
- **Permissions**: glob patterns over the knowledge base for read, write, and write-with-human-approval.
- **Skills**: a role's `skills` names the [Agent Skills](https://agentskills.io/home) it may load, and `scripts` (`never`/`approval`/`free`) sets how it may run one's bundled scripts. Wiring these into a real agent lives in `pydantic_squads.product` (see below).

## Quick look

```python
from pydantic_squads import HUMAN, InteractionMode, Role, Squad

lead = Role(
    id="lead",
    name="Lead",
    mission="Help the human decide what to do next.",
    responsibilities=["Discuss options with the human", "Delegate research"],
    out_of_scope=["Making the final decision"],
    mode=InteractionMode.CONVERSATIONAL,
    talks_to=[HUMAN, "researcher"],
    delivers="An approved decision.",
)
# ... define "researcher" with mode=InteractionMode.DELEGATE

squad = Squad(name="Product", roles=[lead, researcher])
print(squad.instructions_for("lead"))
```

Roles written in another language can use a matching `PromptTemplate` (`PT_BR` ships built in):

```python
from pydantic_squads import PT_BR, Squad
squad = Squad(name="Produto", roles=[...], template=PT_BR)
```

## Product squad

`pydantic_squads.product` ships a ready-made squad — Growth PM, HX
researcher, Product Owner — with typed hand-off contracts (see ADR 0003).
Consuming projects supply only a knowledge base; roles and contracts are
fixed.

```python
from pydantic_squads.product import build_product_squad

squad = build_product_squad(language="en")  # or "pt-BR"
print(squad.instructions_for("growth_pm"))
```

### Running it (the `ai` extra)

`pip install "pydantic-squads[ai]"` (backed by [pydantic-ai-slim](https://ai.pydantic.dev),
not the full `pydantic-ai` package) assembles the squad into real agents:
`ProductSquad` talks to the Growth PM, which can consult HX (cited findings,
validated against the knowledge base) and write notes within its
`Permissions`. A write to a `write_with_approval` path pauses the run and
hands you back a `DeferredToolRequests` instead of crashing, so a human
decides before anything is written. HX itself cannot request approval — see
[ADR 0004](docs/adr/0004-hx-cannot-request-write-approval.md).

```python
from pydantic_ai import DeferredToolRequests

from pydantic_squads.product import MarkdownKnowledgeBase, Revision
from pydantic_squads.product.assembly import ProductSquad

kb = MarkdownKnowledgeBase("./vault")  # a folder of Obsidian-style .md notes
squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="B2B tool for small logistics companies. Primary persona: dispatch manager.",
)

reply = squad.chat("Users are dropping off during signup, what do we know?")
print(reply)  # the Growth PM may consult HX before answering

# Once the conversation has enough to work with:
bet = squad.close_bet()
if isinstance(bet, DeferredToolRequests):
    ...  # resolve bet.approvals, then squad.close_bet(deferred_tool_results=...)

# A human reviews `bet` outside this library. Only pass it on once approved:
outcome = squad.submit_bet(bet)

# If the Product Owner sends it back, the Growth PM revises it and submit_bet
# returns a Revision (the new Bet plus the PO's SendBack) instead of
# resubmitting automatically — a human sees why, then approves the revision
# before it reaches the Product Owner.
while isinstance(outcome, Revision):
    print(outcome.send_back.reason, outcome.send_back.questions)
    ...  # a human reviews outcome.bet before resubmitting it
    outcome = squad.submit_bet(outcome.bet)

# outcome is now a Backlog (or a DeferredToolRequests, if the revision itself
# needed write approval).
```

### Skills (the `skills` extra)

Each role can load [Agent Skills](https://agentskills.io/home) — `SKILL.md`
packages with `references/`, `assets/` and `scripts/` — scoped to its own
`Role.skills`; the Growth PM, HX and the Product Owner each ship one
(`prioritization`, `evidence-classification`, `user-stories`), and a
project can add its own. `pip install "pydantic-squads[skills]"` pulls in
[pydantic-ai-skills](https://github.com/dougtrajano/pydantic-ai-skills),
used instead of Pydantic AI's own built-in `Skills` because that one only
loads a `SKILL.md`'s instructions, not the files it points to — see
[ADR 0005](docs/adr/0005-pydantic-ai-skills-for-bundled-files.md).

```python
squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="...",
    skills_dirs=["./skills"],  # supplements the library's own; omit for none
)
```

A role never sees a skill it did not declare, even one from the same
directory. `Role.scripts` (default `"approval"`) governs `run_skill_script`
the same way `write_with_approval` governs a note write: `"never"` removes
the tool, `"approval"` defers it as a `DeferredToolRequests`, `"free"` runs
it unwrapped. Reading a skill's bundled files with `read_skill_resource` is
always free.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md).

## Related

[pydantic-team](https://github.com/Etiqa/pydantic-team) provides runtime team patterns (hierarchical, collaborative) for Pydantic AI. The two are complementary: roles assembled by `pydantic-squads` are regular Pydantic AI agents.

## Development

```bash
uv sync  # add --extra ai for tests/test_product_assembly.py, --extra skills for tests/test_product_skills.py
uv run pytest
```

## License

MIT
