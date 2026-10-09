# 0018. The notes the squad writes are Markdown for people

Status: accepted

## Context

The squad writes four notes by code: the synthesis, the decision, the
approved brief and the Designer's founder questions. They were written for
whoever came first. The brief note was the `Brief` as JSON inside a `.md`
file, so the document a person approved was the one they could not read in
their vault. The others were Markdown, but flat: an opinion was a list of
`- Risk:` and `- Source:` lines, roles appeared by id (`growth_pm`), and
every label was English even in a squad that answers in Portuguese.

A consuming project proposed the fix for the brief: a `to_markdown()` with
its sections, a decision line, criteria as checkboxes, and the JSON kept in
a file of its own. Its labels were Portuguese and its time zone was São
Paulo, both fixed in code.

## Decision

- **Every note the runtime writes is Markdown laid out for reading.** One
  `#` title, one section per field, lists as lists, acceptance criteria as
  `- [ ]` checkboxes, the request and the human's notes as blockquotes.
- **One module renders them: `pydantic_squads.product.notes`.**
  `brief_note`, `decision_note`, `synthesis_note` and
  `founder_questions_note`. It imports only pydantic (ADR 0001).
  `committee.synthesis_note` moved there.
- **Labels follow the squad's `language`.** `en` and `pt-BR`, the same two
  `ProductSquad` already takes. What a model or the human wrote is left as
  written.
- **Roles appear by display name** (`Growth PM`), taken from the role.
  Frontmatter and contracts keep the ids.
- **Times are in the local time of the machine that writes the note.**
  The exact instant stays in the frontmatter (`decided_at`, ISO 8601 with
  its offset). No time zone is configured anywhere.
- **Data lives next to the note, not in it.** `approve()` also writes
  `squad/briefs/<brief_id>.json`, a `BriefRecord`, and the brief note's
  `data` frontmatter names it. A `.json` file is not a note: it is never a
  search result.
- **Agents are told the same thing.** The `write_note` tool's description
  asks for a title, sections and lists in a `.md` note, and never raw JSON.
  This is a prompt, so it is not enforced.

## Consequences

- Reading a brief from its `.md` body breaks (0.2 → 0.3, in the README's
  migration table). Read the `.json`.
- The body of a note is for people: its wording and layout may change in
  any version. Code reads the frontmatter, the `.json`, or the objects
  `ProductSquad` returns.
- A third language needs one more entry in the labels of `notes.py`.
- The same instant reads differently on machines in different time zones.
- `chat`'s synthesis panel keeps its own, shorter rendering in English
  (ADR 0017).
