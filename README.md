# pydantic-squads

[Português](README.pt-BR.md)

Declarative, validated agent squads on top of [Pydantic AI](https://ai.pydantic.dev).

> Early stage (pre-alpha): the declarative core and the ready-made product squad both run today, but the API will change. Not affiliated with the Pydantic team.

Most multi-agent frameworks focus on how agents *run*. `pydantic-squads` focuses on how a squad is *defined*: who each agent is, what it must not do, who it talks to, what it may write, and what it hands off to whom. Definitions are plain Pydantic models, so they are validated at construction time and testable without calling an LLM.

It also ships a ready-made [product squad](#product-squad) that runs end to end on Pydantic AI: from a conversation with the founder to a bet, a backlog of stories, and a clickable HTML prototype.

## Installation

Not on PyPI yet; install from GitHub. Requires Python 3.10+.

```bash
pip install "pydantic-squads @ git+https://github.com/dansaletti/pydantic-squads"
```

The core depends only on `pydantic`. Optional extras, combined as
`"pydantic-squads[ai,skills] @ git+https://github.com/dansaletti/pydantic-squads"`:

| Extra | Adds |
|-------|------|
| `ai` | Runs the product squad as real Pydantic AI agents (`pydantic-ai-slim`) |
| `skills` | Per-role Agent Skills (`pydantic-ai-skills`) |
| `observability` | The `pydantic-squads trace` local viewer (`rich`); use with `ai` |
| `otel` | Opt-in OpenTelemetry / Logfire export (`logfire`); use with `ai` |

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
researcher, Product Owner, Designer — with typed hand-off contracts (see
ADR 0003). The flow is conversation → `Bet` → `Backlog` → `Prototype`.
Consuming projects supply only a knowledge base; roles and contracts are
fixed.

```python
from pydantic_squads.product import build_product_squad

squad = build_product_squad(language="en")  # or "pt-BR"
print(squad.instructions_for("growth_pm"))
```

### Running it (the `ai` extra)

The `ai` extra (see [Installation](#installation); backed by
[pydantic-ai-slim](https://ai.pydantic.dev), not the full `pydantic-ai`
package) assembles the squad into real agents:
`ProductSquad` talks to the Growth PM, which can consult HX (cited findings,
validated against the knowledge base) and write notes within its
`Permissions`. A write to a `write_with_approval` path pauses the run and
hands you back a `DeferredToolRequests` instead of crashing, so a human
decides before anything is written. HX itself cannot request approval — see
[ADR 0004](docs/adr/0004-hx-cannot-request-write-approval.md). Pass
`language="pt-BR"` to get the instruction labels in Portuguese (default
`"en"`).

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

### Designing it

The Product Owner marks each story `needs_design` (required, no default).
`design()` hands the backlog to the Designer, which turns every story that
needs design into a self-contained, mobile-first HTML prototype in
`squad/design/<cycle_id>/`, consulting HX about users along the way. A
deterministic gate checks that every such story is on some screen before
the prototype is accepted. See
[ADR 0007](docs/adr/0007-designer-role.md).

```python
from pydantic_squads.product import Prototype

result = squad.design(outcome)  # None if no story needs design
if isinstance(result, DeferredToolRequests):
    # The first time, the Designer proposes a design system; writing to
    # design-system/** waits for your approval.
    result = squad.design(deferred_tool_results=result.build_results(approve_all=True))

if isinstance(result, Prototype):
    print(result.html_path)  # open it in a browser
    for q in result.founder_questions:  # also in questions.md, next to the HTML
        print(q.question, "— default:", q.suggested_default)
    # Brand, tone and positioning are yours to decide: keys are the questions'
    # text, and unanswered ones keep the Designer's suggested default.
    result = squad.design(outcome, answers={"Which tone?": "Friendly, informal"})
```

A story too ambiguous to design comes back as a `SendBack`, to you, not
automatically to the Product Owner.

### Skills (the `skills` extra)

Each role can load [Agent Skills](https://agentskills.io/home) — `SKILL.md`
packages with `references/`, `assets/` and `scripts/` — scoped to its own
`Role.skills`; every role ships one (`prioritization`,
`evidence-classification`, `user-stories`, `prototyping`), and a
project can add its own. The `skills` extra pulls in
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

## Observability

See [ADR 0006](docs/adr/0006-observability-and-checkpointing.md). A cycle
is one conversation → `Bet` → `Backlog` → `Prototype` arc. Pass `trace_dir` to
`ProductSquad` to record every call as spans (agent, model/tool calls,
tokens, real cost, status) into `{trace_dir}/{cycle_id}.jsonl`, one
append-only file per cycle — including HX's own spans, nested under the
Growth PM's `consult_hx` tool span. A stable `cycle_id` is generated either
way, since it's also written into the frontmatter of every closed `Bet`'s
note (`squad/bets/<bet_version_id>.md`, alongside `schema_version` and, on
a revision, `previous_bet_version_id`).

```python
from pydantic_ai import UsageLimits

squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="...",
    usage_limits=UsageLimits(request_limit=20),  # None (default) is unlimited
    trace_dir="./traces",
)
```

Reload a past conversation and keep going with `chat()`. The `cycle_id` is
the name of its trace file (`{trace_dir}/<cycle_id>.jsonl`), and it is also
in the frontmatter of the cycle's Bet notes:

```python
squad = ProductSquad(kb, model="openai:gpt-4o", context="...", trace_dir="./traces")
squad.resume(cycle_id)
squad.chat("...")
```

### Local trace viewer (the `observability` extra)

The `ai` and `observability` extras add a `rich`-based CLI:

```bash
pydantic-squads trace <cycle_id> --trace-dir ./traces --budget-tokens 20000
```

It prints a per-span timeline, per-agent duration/tokens/cost, and flags:
slow spans, HX retries caused by a source that doesn't exist in the
knowledge base, Product Owner send-backs, pending human approvals, and
input tokens over `--budget-tokens` (checked both per cycle and per span).
`--trace-dir` defaults to `$PYDANTIC_SQUADS_TRACE_DIR`, or `traces`;
`--slow-threshold-ms` sets what counts as slow (default 5000).

### OpenTelemetry / Logfire export (the `otel` extra, off by default)

The `ai` and `otel` extras add an explicit opt-in:

```python
from pydantic_squads.product.otel import enable_otel

enable_otel(send_to_logfire=True)  # or False, to export to your own OTel collector
```

> **Warning:** this sends full conversation content — user messages, model
> replies, tool call arguments, including knowledge-base note contents — to
> whatever OpenTelemetry backend you configure. It is off by default and
> must be enabled explicitly; review what that backend stores and who can
> access it first. It's independent of the local JSONL/CLI trace above,
> which never leaves the local machine.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md).

## Related

[pydantic-team](https://github.com/Etiqa/pydantic-team) provides runtime team patterns (hierarchical, collaborative) for Pydantic AI. The two are complementary: roles assembled by `pydantic-squads` are regular Pydantic AI agents.

## Development

```bash
uv sync  # add --extra ai for tests/test_product_assembly.py and tests/test_product_observability.py,
         # --extra skills for tests/test_product_skills.py,
         # --extra observability for tests/test_cli.py, --extra otel for tests/test_product_otel.py
uv run pytest
uv run pytest --cov=pydantic_squads --cov-report=term-missing  # coverage stays at 100%
```

Project rules for contributors and coding agents (ADRs, test conventions,
which modules may import what) are in [AGENTS.md](AGENTS.md).

## License

MIT
