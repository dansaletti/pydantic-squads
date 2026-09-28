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

`pip install "pydantic-squads[ai]"` assembles the squad into real [Pydantic
AI](https://ai.pydantic.dev) agents: `ProductSquad` talks to the Growth PM,
which can consult HX (cited findings, validated against the knowledge base)
and write notes within its `Permissions`. A write to a `write_with_approval`
path pauses the run and hands you back a `DeferredToolRequests` instead of
crashing, so a human decides before anything is written.

```python
from pydantic_ai import DeferredToolRequests

from pydantic_squads.product import MarkdownKnowledgeBase
from pydantic_squads.product.assembly import ProductSquad

kb = MarkdownKnowledgeBase("./vault")  # a folder of Obsidian-style .md notes
squad = ProductSquad(kb, model="openai:gpt-4o")

reply = squad.chat("Users are dropping off during signup, what do we know?")
print(reply)  # the Growth PM may consult HX before answering

# Once the conversation has enough to work with:
bet = squad.close_bet()
if isinstance(bet, DeferredToolRequests):
    ...  # resolve bet.approvals, then squad.close_bet(deferred_tool_results=...)

# A human reviews `bet` outside this library. Only pass it on once approved:
outcome = squad.submit_bet(bet)  # -> Backlog, SendBack, or DeferredToolRequests
```

`submit_bet` relays a `SendBack` from the Product Owner to the Growth PM to
revise the bet automatically, up to `max_send_backs` times (default 3).

## Roadmap

See [docs/roadmap.md](docs/roadmap.md).

## Related

[pydantic-team](https://github.com/Etiqa/pydantic-team) provides runtime team patterns (hierarchical, collaborative) for Pydantic AI. The two are complementary: roles assembled by `pydantic-squads` are regular Pydantic AI agents.

## Development

```bash
uv sync
uv run pytest
```

## License

MIT
