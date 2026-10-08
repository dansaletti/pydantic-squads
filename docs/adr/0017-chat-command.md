# 0017. `pydantic-squads chat`: the squad as a terminal session

Status: accepted

## Context

Running the product squad took a program around `ProductSquad`: a loop
that reads a line, a way to show a synthesis, a prompt for each write that
needs approval, a table of what the cycle cost. The library shipped one as
an example, and a consuming project had written another. The two were the
same program, about 380 lines each, differing in four values: where the
vault is, which note holds the product context, the language, and where
traces go. A fix to one did not reach the other: showing the cost after
the Gantt chart was implemented twice.

Three users needed it (that project, another consumer, and the example),
and none of what they needed was specific to a product.

## Decision

- **The session is a command of the library: `pydantic-squads chat
  VAULT`.** It takes the vault, the product context (text or a file), the
  language, the trace directory, and the models. `ChatSession` in
  `pydantic_squads.product.chat` is the session; the CLI builds the squad
  and runs it.
- **Commands are in English**, like the rest of the public API: `/close`,
  `/review`, `/approve`, `/adjust`, `/reject`, `/submit`, `/content`,
  `/design`, `/gantt`, `/cost`, `/resume`, `/help`, `/quit`. `--language`
  still sets the language the agents answer in. Translating the commands
  was left out until someone needs it.
- **With no `--model` it uses the recommended Claude Code setup** (ADR
  0016), and says so. `--model` replaces it; `--pm-model`, `--hx-model` and
  `--role-model ROLE=MODEL` change single roles.
- **It needs the `ai` and `observability` extras**, the same as `trace`:
  the session renders with `rich`. `cli.py` imports it lazily.
- **Cost comes from the squad's spans in memory**, through
  `ProductSquad.spans` and `report_from_spans`, so `/cost` and `/gantt`
  work with or without a trace directory. `/resume` still needs one.
- **The example it replaces is removed.** `examples/committee_chat.py`
  would have been a third copy.

## Consequences

- A consuming project needs no code to talk to the squad: a vault and one
  command. A project that wants its own interface still builds on
  `ProductSquad`, or on `ChatSession` with its own `ask`.
- The commands are public API now: renaming one changes what people type.
- The session is tested like the rest: a fake model plays every agent, the
  input is scripted, and the output is captured.
- A model or network failure is shown and the session continues; a command
  used out of order says why. Neither ends the session.
- `ProductSquad.spans` and `report_from_spans` are new public surface.
