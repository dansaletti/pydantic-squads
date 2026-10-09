# pydantic-squads

[Português](README.pt-BR.md)

Declarative, validated agent squads on top of [Pydantic AI](https://ai.pydantic.dev).

> Early stage (pre-alpha): the declarative core and the ready-made product squad both run today, but the API will change. Not affiliated with the Pydantic team.

Most multi-agent frameworks focus on how agents *run*. `pydantic-squads` focuses on how a squad is *defined*: who each agent is, what it must not do, who it talks to, what it may write, and what it hands off to whom. Definitions are plain Pydantic models, so they are validated at construction time and testable without calling an LLM.

It also ships a ready-made [product squad](#product-squad) that runs end to end on Pydantic AI: from a conversation with a neutral Facilitator, through a committee of PMs and one human decision, to a backlog of stories, a clickable HTML prototype and launch content.

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

`pydantic_squads.product` ships a ready-made squad with typed hand-off
contracts (see ADR 0003 and [ADR 0013](docs/adr/0013-pm-committee-with-a-single-human-gate.md)). Consuming projects supply
only a knowledge base; roles and contracts are fixed.

New to the project? [docs/architecture.md](docs/architecture.md) walks
through the flow, each role's boundaries and why it is built this way.

| Role | What it does |
| --- | --- |
| Facilitator | The only role that talks to you. Makes the request clear, picks the PMs to hear, and consolidates what they say. Gives no opinion |
| Growth PM, Product PM, Marketing PM | The committee. Each gives an `Opinion` from its own view: metrics and experiments, journeys and scope, positioning and messaging |
| HX researcher | A read-only query tool over the knowledge base: cited findings, each classified as evidence, assumption or gap |
| Product Owner | Turns an approved `Brief` into a `Backlog`. Takes nothing else |
| Designer | Turns the stories that need design into an HTML `Prototype` |
| Social Media | Turns the same `Brief` into a `ContentPack`, under the Marketing PM |

The flow is conversation → `Triage` → `Opinion`s in parallel → `Synthesis`
→ your decision → `Brief` → `Backlog` → `Prototype`, and the same `Brief` →
`ContentPack`.

```python
from pydantic_squads.product import build_product_squad

squad = build_product_squad(language="en")  # or "pt-BR"
print(squad.instructions_for("facilitator"))
```

### Running it (the `ai` extra)

The `ai` extra (see [Installation](#installation); backed by
[pydantic-ai-slim](https://ai.pydantic.dev), not the full `pydantic-ai`
package) assembles the squad into real agents.

```python
from pydantic_ai import DeferredToolRequests

from pydantic_squads.product import BriefRejection, MarkdownKnowledgeBase
from pydantic_squads.product.assembly import ProductSquad

kb = MarkdownKnowledgeBase("./vault")  # a folder of Obsidian-style .md notes
squad = ProductSquad(
    kb,
    model="openai:gpt-4o",
    context="B2B tool for small logistics companies. Primary persona: dispatch manager.",
)

# 1. Talk to the Facilitator until the request is clear. It may consult HX.
reply = squad.chat("I want a fake-door landing page for route sharing")
print(reply)

# 2. Close the conversation. The Facilitator triages it, the PMs it picks
#    give their opinions in parallel, and you get a Synthesis back.
synthesis = squad.close_request()
if isinstance(synthesis, DeferredToolRequests):
    ...  # resolve it, then squad.close_request(deferred_tool_results=...)

print(synthesis.summary)
for divergence in synthesis.divergences:  # where the PMs disagree, position by position
    print(divergence.topic, divergence.positions)
for gap in synthesis.gaps:  # what HX said the knowledge base does not know
    print(gap.gap, gap.questions, gap.asked_by)
for opinion in synthesis.opinions:  # each PM's opinion, whole
    print(opinion.role, opinion.confidence, opinion.recommendation)
print(synthesis.proposed_brief)

# 3. Decide, once. Pick one:
synthesis = squad.adjust("Make the metric a conversion rate")  # redo the synthesis only
brief = squad.approve("Go ahead")  # the proposed brief, with your decision stamped on it
# squad.reject("Not this quarter")  # ends the request, no brief

# 4. Only an approved Brief reaches the Product Owner.
outcome = squad.submit_brief(brief)
if isinstance(outcome, BriefRejection):
    print(outcome.missing_fields, outcome.reason)
# Otherwise outcome is a Backlog.
```

`squad.review("...")` takes a request to the committee directly, with no
conversation before it.

### Talking to it from a terminal

`pydantic-squads chat` is this whole flow as a terminal session, on a real
model, with no code to write. You need
[Claude Code](https://code.claude.com) installed and logged in (`claude`,
then `/login`) and a folder of markdown notes to use as the knowledge base:

```bash
pip install "pydantic-squads[ai,observability] @ git+https://github.com/dansaletti/pydantic-squads"
pydantic-squads chat PATH/TO/VAULT \
  --context "What your product is and who it is for" \
  --trace-dir ./traces
```

From a clone of this repo, with [uv](https://docs.astral.sh/uv/):
`uv run --extra ai --extra observability pydantic-squads chat PATH/TO/VAULT`.

Type your request, then:

| Command | What it does |
| --- | --- |
| `/close` | Close the conversation and take the request to the committee |
| `/review TEXT` | Take TEXT to the committee directly, with no conversation |
| `/approve [NOTES]`, `/adjust NOTES`, `/reject REASON` | Your decision on the synthesis |
| `/submit` | Hand the approved Brief to the Product Owner |
| `/content`, `/design` | Have Social Media write the content, or the Designer the prototype |
| `/gantt`, `/cost` | Draw the cycle with its cost, or show only the cost per agent |
| `/resume CYCLE_ID` | Continue an earlier conversation (needs `--trace-dir`) |
| `/help`, `/quit` | The list of commands; leave, showing the cost |

A write that needs your approval is shown and waits for your yes or no.
With no model option the session runs the
[recommended setup](#recommended-setup) on your Claude Code login, which
counts against your plan's limits. `--model` takes any Pydantic AI model
string instead, to run on an API key; `--pm-model`, `--hx-model` and
`--role-model ROLE=MODEL` change single roles. `--context` also takes a
path to a file, `--language pt-BR` makes the agents answer in Portuguese,
`--skills` gives the roles the library's skills, and `--config FILE` adds
[your project's own](#project-skills). See
[ADR 0017](docs/adr/0017-chat-command.md).

What holds this together, by code and not by prompt:

- **The Facilitator is neutral.** Its conversational agent has no tool
  that reaches a PM, the agent that writes the synthesis has no tool at
  all, and a `Synthesis` has no field for a recommendation of its own.
- **The PMs do not debate.** Each gives its opinion in a run of its own,
  with no message history and no sight of the others. The role on an
  opinion is stamped by the runtime, and a source that is not a note in
  the knowledge base is refused.
- **At most one rebuttal.** If the first synthesis finds divergences, the
  PMs cited in them reply once and the synthesis is redone. What still
  diverges stays visible. There is no loop.
- **You see the raw material.** The synthesis carries the original
  opinions whole, the replies, and every gap HX reported with the question
  that surfaced it. The Facilitator groups gaps that say the same thing,
  and code makes sure none is dropped; `synthesis.raw_gaps` has them in
  HX's words. It is also written to
  `squad/committee/<cycle_id>/synthesis-<n>.md`.
- **The decision is data.** `approve()` calls no model: it stamps a
  `HumanDecision` and writes the `Brief` to `squad/briefs/<brief_id>.md`,
  as Markdown you can read, with the same brief as data in
  `<brief_id>.json` next to it
  ([ADR 0018](docs/adr/0018-notes-are-markdown-for-people.md)).
  A brief with a field missing, or without an approved decision, is
  rejected before the Product Owner's model is called
  ([ADR 0011](docs/adr/0011-brief-is-the-product-owners-only-door.md)).
- **HX is a read-only query tool.** Every `consult_hx` call is a fresh run
  with no memory of the previous one, and it never writes
  ([ADR 0010](docs/adr/0010-hx-is-a-read-only-query-tool.md)).
  `ProductSquad` wraps the knowledge base you give it in a
  `SerializedKnowledgeBase`, so writes happen one at a time.

The Facilitator can write to `docs/**` and `assumptions/**` with your
approval. Such a write pauses the run and hands you back a
`DeferredToolRequests` instead of crashing, so you decide before anything
is written; pass its resolution back as `deferred_tool_results` on the same
method. After `approve()` or `reject()`, the next `chat()` starts a new
request, with a new `cycle_id`. Pass `language="pt-BR"` to get the
instruction labels, and the notes the squad writes, in Portuguese
(default `"en"`).

A request heard by three PMs costs a triage, three opinions (each with its
own HX consultations) and a synthesis, plus one more round when they
diverge. `usage_limits` caps every run. To keep each call small, searching
the knowledge base returns excerpts of the best matches and a role reads
the notes it needs
([ADR 0015](docs/adr/0015-search-returns-excerpts.md)). What HX already
answered the Facilitator is handed to the PMs, so the same question is not
put to HX once per PM.

#### Recommended setup

There is no configuration file: the squad is configured by the arguments
of `ProductSquad`. Roles can run on different models. `models` maps a role
id to its model, and every role not named uses `model`
([ADR 0016](docs/adr/0016-shared-evidence-brevity-and-a-model-per-role.md)).

The library ships one tested setup for Claude Code as a preset. It is what
`pydantic-squads chat` uses by default:

```python
from pydantic_squads.product.claude_code import RECOMMENDED_MODEL, RECOMMENDED_ROLE_MODELS

squad = ProductSquad(
    kb,
    model=RECOMMENDED_MODEL,  # "claude-code:sonnet": Facilitator, Product Owner, Designer, Social Media
    models=RECOMMENDED_ROLE_MODELS,  # PMs on "claude-code:sonnet:high", HX on "claude-code:haiku"
    context="...",
)
```

The PMs, which judge, run on Sonnet with extended thinking; HX, which
retrieves and classifies, on Haiku. On one real vault, the same kind of
request went from an estimated US$ 4.74 before any of this to US$ 0.64 with
this setup, from the conversation to the backlog. It is a preset, not a
default: `ProductSquad(kb, model=...)` alone runs every role on one model.
To change one role, pass your own mapping, for example
`models={**RECOMMENDED_ROLE_MODELS, "hx": "claude-code:sonnet"}`.

### Running on your Claude Code login (no API key)

If you have [Claude Code](https://code.claude.com) installed and logged in
(`claude`, then `/login`), the squad can run on that login instead of an API
key: pass `model="claude-code"` (Claude Code's default model) or
`model="claude-code:sonnet"` / `"claude-code:opus"`. A third part sets the
reasoning effort (`low`, `medium`, `high`, `xhigh`, `max`):
`"claude-code:sonnet:high"` is Sonnet with extended thinking, which reasons
longer and costs more output tokens. Every agent request
becomes a tool-less `claude -p` call; the squad's tools, permissions,
approvals and validators still run in Python, unchanged (ADR 0008).

```python
import os

squad = ProductSquad(
    kb,
    model=os.environ.get("SQUAD_MODEL", "claude-code:sonnet"),  # or "anthropic:claude-sonnet-4-5"
    context="...",
)
```

`ANTHROPIC_API_KEY` is removed from the CLI's environment so the login is
used; for more control build the model yourself:
`ClaudeCodeModel("sonnet", timeout=900, extra_args=[...])` from
`pydantic_squads.product.claude_code`.

> **Local, personal use only.** Anthropic does not allow third-party
> products to offer claude.ai login or its rate limits to their users.
> Use this backend to run the squad for yourself; anything you ship to
> other people uses an API key. It is also slower than the API (one CLI
> process per request), counts against your plan's usage limits, and
> works best with Sonnet or Opus: small models follow the tool-calling
> protocol less reliably.

Traces of this backend show the tokens and cost Claude Code reports for
each call. Input tokens are the whole prompt, cached tokens included, and
the cost is an estimate at API list prices: a way to compare cycles, not
something your subscription is charged.

### Designing it

The Product Owner marks each story `needs_design` (required, no default).
`design()` hands the backlog to the Designer, which turns every story that
needs design into a self-contained, mobile-first HTML prototype in
`squad/design/<cycle_id>/`, consulting HX about users and the Marketing PM
about brand along the way. A
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
    # What reaches you is what the squad could not answer: an HX gap, or a
    # brand question the Marketing PM found nothing about in the knowledge
    # base. Keys are the questions' text, and unanswered ones keep the
    # Designer's suggested default.
    result = squad.design(outcome, answers={"Which tone?": "Friendly, informal"})
```

A story too ambiguous to design comes back as a `SendBack`, to you, not
automatically to the Product Owner.

### Writing the content

The Marketing PM owns positioning, tone, brand and naming. Other roles ask
it through `consult_pm_marketing`, and it answers from the knowledge base,
with sources, or says the knowledge base does not settle the question. Only
then does a brand question reach you. Social Media works under it:
`produce_content()` takes the same approved `Brief` and writes landing-page
copy and posts to `squad/content/<cycle_id>/`. See
[ADR 0012](docs/adr/0012-marketing-pm-owns-brand-and-social-media-executes.md).

```python
from pydantic_squads.product import ContentPack

pack = squad.produce_content(brief)  # a BriefRejection if the brief is not approved
if isinstance(pack, ContentPack):
    for piece in pack.pieces:
        print(piece.kind, piece.channel, piece.path)  # files in the knowledge base
    print(pack.open_questions)  # brand questions nobody could answer
```

Nothing is published: reviewing and posting the content is yours to do.

### Skills (the `skills` extra)

Each role can load [Agent Skills](https://agentskills.io/home) — `SKILL.md`
packages with `references/`, `assets/` and `scripts/` — scoped to its own
`Role.skills`; every role but the Facilitator ships one (`prioritization`, `story-mapping`,
`evidence-classification`, `user-stories`, `prototyping`, `social`), the
Product Owner also ships `story-mapping`, the Designer ships `impeccable` (adapted
from [impeccable](https://github.com/pbakaus/impeccable), Apache-2.0), the Growth PM,
the Marketing PM and Social Media share twelve growth-marketing skills from
[marketingskills](https://github.com/coreyhaines31/marketingskills) (eight,
three and one; MIT,
see `src/pydantic_squads/product/skills/THIRD_PARTY_NOTICE.md`), and a
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

#### Project skills

The library ships the mechanism; your project decides which skills each
role uses ([ADR 0019](docs/adr/0019-project-skills-and-typed-skill-tools.md)).
Third-party skills are not versioned in this repository: install them
locally, then map them to roles in a config file.

```bash
pydantic-squads skills install phuryn/pm-skills
pydantic-squads skills install nextlevelbuilder/ui-ux-pro-max-skill
pydantic-squads skills install Leonxlnx/taste-skill
pydantic-squads chat VAULT --config skills.yaml
```

`skills install` takes a GitHub `owner/name` or an `https://` URL and
clones it into `~/.squads/skills/` (`--dir` changes that, `--update`
fast-forwards). The config is the `skills:` section of a YAML file:

```yaml
skills:
  paths:                       # searched however deep
    - ~/.squads/skills/pm-skills
    - ~/.squads/skills/ui-ux-pro-max-skill
    - ~/.squads/skills/taste-skill
  roles:                       # added to the skills each role already has
    pm_product: [pm-product-discovery/*, pm-market-research/*]
    designer: [ui-ux-pro-max, design-taste-frontend]
  commands:                    # a repository's workflow files, as skills
    pm_product: [pm-product-discovery/commands/*, pm-market-research/commands/*]
  rules:                       # added to each role's principles
    designer:
      - "Build the foundation with ui-ux-pro-max first, then apply design-taste-frontend"
  tools:                       # a skill's script, as a typed tool
    - name: persist_design_system
      roles: [designer]
      skill: ui-ux-pro-max
      script: scripts/search.py
      description: Generate the design system and save it in the knowledge base.
      fixed_args: [--design-system, --persist, --project-name, "My Product", --output-dir, ~/my-vault]
      params:
        - {name: query, required: true}
        - {name: page, flag: --page}
```

[`examples/skills.yaml`](examples/skills.yaml) is the complete version. In
Python, pass the same thing as `ProductSquad(..., skills=SkillsConfig(...))`
or `skills=load_skills_config("skills.yaml")`, both from
`pydantic_squads.product.skills_config`.

- **A pattern** under `roles` is a skill's name (the `name` in its
  `SKILL.md` frontmatter) or a glob on where it sits under one of the
  `paths`; `!pattern` leaves matches out. A pattern that matches nothing
  is an error.
- **Commands**: some repositories ship workflows as slash commands, a
  Markdown file outside any skill that chains several skills (`/discover`
  in pm-skills). There are no slash commands here, so a file picked under
  `commands` reaches the role as a skill named after the file (`discover`),
  holding the workflow as written. It is read from the installed file each
  time the squad is built: `skills install --update` is all it takes to
  follow a change upstream.
- **Progressive disclosure**: an agent's prompt lists only the name and
  description of its own role's skills. It loads one's instructions with
  `load_capability` and reads its files with `read_skill_resource`, which
  never leaves the skill's folder.
- **Scripts**: a project skill's scripts run only as the tools declared
  under `tools`. The model fills `params`, validated by a Pydantic model
  (types, `choices`, `minimum`/`maximum`); `fixed_args` are yours, so the
  model never picks a destination. The script runs with no shell, a
  `timeout` (30 seconds by default) and the skill's folder as working
  directory.
- **Approval**: a tool pauses for your yes or no unless it says
  `approval: false`, which is for a script that writes nothing. Only the
  Facilitator and the Designer can pause, so only they can have a tool
  that needs approval.

The skills this was built for, none of which is in this repository:

| Role | Skills | Source | License | Status |
| --- | --- | --- | --- | --- |
| Product PM | `pm-product-discovery`, `pm-market-research` | [phuryn/pm-skills](https://github.com/phuryn/pm-skills) | MIT | Phase 1, in `examples/skills.yaml` |
| Designer | `ui-ux-pro-max` (foundation: tokens, palette, typography, accessibility) | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | MIT | Phase 1, in `examples/skills.yaml` |
| Designer | `design-taste-frontend` (visual direction of a page) | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | MIT | Phase 1, in `examples/skills.yaml` |
| Marketing PM | `pm-marketing-growth` | [phuryn/pm-skills](https://github.com/phuryn/pm-skills) | MIT | Phase 2, not wired |
| Growth PM | `pm-go-to-market` | [phuryn/pm-skills](https://github.com/phuryn/pm-skills) | MIT | Phase 2, not wired |
| Product Owner | `pm-execution` | [phuryn/pm-skills](https://github.com/phuryn/pm-skills) | MIT | Phase 2, not wired |
| Marketing PM or HX | `last30days` (trend listening) | [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) | MIT | Phase 3, not wired |
| Product Owner | OpenSpec (hand-off format for developers) | [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) | MIT | Phase 3, not wired |

HX takes no external skill: it is the squad's source of product knowledge,
and the other roles consult it. A skill is a method, never a source of
facts. Check each repository's license before using it; `skills install`
prints the first line of the one it finds.

## Observability

See [ADR 0006](docs/adr/0006-observability-and-checkpointing.md). A cycle
is one request: the conversation, the committee's round, the decision, and
the backlog, prototype and content made from the brief. Pass `trace_dir` to
`ProductSquad` to record every call as spans (agent, model/tool calls,
tokens, real cost, status) into `{trace_dir}/{cycle_id}.jsonl`, one
append-only file per cycle — including HX's own spans, nested under the
`consult_hx` tool span of the role that consulted it, and a
`human_decision` span for your approval or rejection. A stable `cycle_id`
is generated either way, since it's also written into the frontmatter of
the synthesis notes (`squad/committee/<cycle_id>/`) and of the brief note
(`squad/briefs/<brief_id>.md`).

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
in the frontmatter of the cycle's synthesis and brief notes. Read the current one from
`squad.cycle_id` (`None` until the first call starts a cycle):

```python
squad = ProductSquad(kb, model="openai:gpt-4o", context="...", trace_dir="./traces")
squad.resume(cycle_id)
squad.chat("...")
```

`resume()` restores the Facilitator's conversation. A synthesis that was
waiting for your decision is not restored: call `close_request()` again.
Its notes from before are still in the knowledge base.

A committee round is recorded as one `request` span with its steps under it
(`triage`, `fan_out`, `synthesis`, and `rebuttal` when the PMs diverge),
each agent run inside its step. `squad.gantt().print()` draws the current
cycle as a [terminal Gantt chart](docs/gantt_visualization.md) straight
from memory, with or without `trace_dir`: the PMs' opinions show as
overlapping bars under `fan_out`. See [ADR 0014](docs/adr/0014-request-steps-in-the-trace-and-a-live-gantt.md).

### Local trace viewer (the `observability` extra)

The `ai` and `observability` extras add a `rich`-based CLI:

```bash
pydantic-squads trace <cycle_id> --trace-dir ./traces --budget-tokens 20000
```

It prints a per-span timeline, per-agent duration/tokens/cost, and flags:
slow spans, HX retries caused by a source that doesn't exist in the
knowledge base, brief rejections, Designer send-backs, pending human
approvals, and
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

## Migrating

The API still changes between versions, with no compatibility aliases.
Each breaking change is listed here.

### 0.2 → 0.3

| Before | After |
| --- | --- |
| `squad/briefs/<brief_id>.md` held the `Brief` as JSON: `Brief.model_validate_json(kb.read(path).content)` | The `.md` is Markdown for a person ([ADR 0018](docs/adr/0018-notes-are-markdown-for-people.md)). The data is in `squad/briefs/<brief_id>.json`, named by the note's `data` frontmatter: `BriefRecord.model_validate_json(kb.read(json_path).content).brief` |
| `committee.synthesis_note(synthesis, cycle_id, version)` | `notes.synthesis_note(synthesis, cycle_id, version, language)`, in `pydantic_squads.product.notes` |
| `synthesis-<n>.md`, `decision.md` and `questions.md` had fixed English text such as `- Risk: ...`, `- Asked by: growth_pm` and `- Origin: hx_gap` | Same paths and frontmatter. The body is laid out for reading, names roles by their display name (`Growth PM`), and is in the squad's `language`. Do not parse the body |

### 0.1 → 0.2

| Before | After |
| --- | --- |
| HX had `write_note` and could write under `squad/hx/**` | HX is read-only ([ADR 0010](docs/adr/0010-hx-is-a-read-only-query-tool.md)). Existing notes under `squad/hx/` stay readable; HX reports what it would have noted as findings in its `HXAnswer` |
| `squad.chat()` talked to the Growth PM | It talks to the Facilitator, which gives no opinion ([ADR 0013](docs/adr/0013-pm-committee-with-a-single-human-gate.md)) |
| `bet = squad.close_bet()` | `synthesis = squad.close_request()`, then `brief = squad.approve()` (or `adjust(notes)` / `reject(reason)`) |
| `Bet`, `BetRecord` | Removed. The decision artifact is the `Brief`; the PMs' views are `Opinion`s inside the `Synthesis`. `BriefRecord` replaces `BetRecord` |
| Notes in `squad/bets/<bet_version_id>.md` | `squad/briefs/<brief_id>.md`, plus `squad/committee/<cycle_id>/synthesis-<n>.md` and `decision.md`. Old bet notes stay readable |
| `squad.submit_bet(bet)` | `squad.submit_brief(brief)`, with the `Brief` that `approve()` returns ([ADR 0011](docs/adr/0011-brief-is-the-product-owners-only-door.md)) |
| `Revision` (the Growth PM revising a bet the Product Owner sent back) | Removed. `submit_brief()` returns `Backlog \| BriefRejection`; fix the brief and submit it again |
| The Product Owner's `SendBack` | `BriefRejection(missing_fields, reason)`. `SendBack` is now only the Designer's |
| `submit_bet()` could return a `DeferredToolRequests` | `submit_brief()` never does |
| A trace was a flat list of agent runs | A committee round adds a `request` span with step spans under it, all with `agent="squad"`. The file format is the same |
| `Report.po_send_backs`, "Product Owner send-backs" in `pydantic-squads trace` | `Report.brief_rejections`, "Brief rejections" |
| `GROWTH_PM` was conversational, wrote notes and talked to the Product Owner | It is a task role that only reads. Approved writes to `docs/**` and `assumptions/**` are the Facilitator's |
| `HXAnswer.question` was whatever HX wrote | It is the caller's question, word for word |
| `build_product_squad()` had 4 roles | It has 8, in this order: `facilitator`, `growth_pm`, `pm_product`, `pm_marketing`, `hx`, `product_owner`, `designer`, `social_media`. `Span.agent` accepts the new ids too, and the squad adds the `product_owner_has_one_door` policy |
| `FounderQuestion(origin="positioning", ...)` | Add `marketing_question`, the question put to the Marketing PM. The Designer asks it before asking you ([ADR 0012](docs/adr/0012-marketing-pm-owns-brand-and-social-media-executes.md)) |
| The Growth PM had `product-marketing`, `marketing-psychology`, `launch` and `social` | The first three are the Marketing PM's, and `social` is Social Media's |
| The Designer listed `product_owner` in `talks_to` | It lists `hx` and `pm_marketing` |
| `ProductSquad(kb).kb is kb` | `ProductSquad(kb).kb` is a `SerializedKnowledgeBase` around `kb`. To share one writer between squads, wrap first with `SerializedKnowledgeBase.wrap(kb)` and pass the wrapper |

## Roadmap

See [docs/roadmap.md](docs/roadmap.md).

## Related

[pydantic-team](https://github.com/Etiqa/pydantic-team) provides runtime team patterns (hierarchical, collaborative) for Pydantic AI. The two are complementary: roles assembled by `pydantic-squads` are regular Pydantic AI agents.

## Development

```bash
uv sync  # add --extra ai for tests/test_product_assembly.py, tests/test_product_committee.py,
         # tests/test_product_marketing.py and tests/test_product_observability.py,
         # --extra skills for tests/test_product_skills.py, tests/test_product_project_skills.py,
         # tests/test_product_skill_registry.py, tests/test_product_skill_tools.py
         # and tests/test_product_skills_config.py,
         # --extra observability for tests/test_cli.py and tests/test_product_chat.py,
         # --extra otel for tests/test_product_otel.py
uv run pytest
uv run pytest --cov=pydantic_squads --cov-report=term-missing  # coverage stays at 100%
```

Project rules for contributors and coding agents (ADRs, test conventions,
which modules may import what) are in [AGENTS.md](AGENTS.md).

## License

MIT
