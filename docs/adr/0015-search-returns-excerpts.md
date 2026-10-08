# 0015. Search returns excerpts, and committee syntheses are not search results

Status: accepted

## Context

The first real committee run (three PMs, on a 26-note vault) used 1.19
million input tokens over 38 model calls. Measured call by call, the cost
was in the size of each call, not in how many there were:

- `search_notes` returned whole notes. The search matches any word of the
  query, so on a small vault a query of several words returned most of the
  vault in full: about 95,000 characters for one search.
- An HX consultation makes two or three searches. Its model calls went
  from 7,000 input tokens to between 47,000 and 65,000 once the results
  came back. Each PM made searches of its own on top of consulting HX.
- A search made in the first turn of the conversation stayed in its
  history and was sent again on every later turn.

The run also wrote a 64 KB synthesis note into the knowledge base. It
repeats every opinion of its round, so it matches any query about the
request, and it is larger than the notes it was made from. Left
searchable, it would be returned on every later search, and HX could cite
it as if it were evidence about users.

## Decision

- **`search_notes` and `list_by_tag` return excerpts.** Each result is a
  `NoteExcerpt`: the note's path, tags and size, and up to two short
  excerpts around what matched (for a tag listing, the beginning of the
  note). A search returns the 8 best matches. `read_note` still returns
  the whole note, and the tools say to read a note before relying on it or
  citing it.
- **The cut is made in the tool, not in the knowledge base.**
  `KnowledgeBase.search` still returns `Note`s, so a knowledge base written
  by a consuming project keeps working. `excerpt()` is a pure function in
  `product.knowledge`.
- **A committee synthesis is never a search result.**
  `squad/committee/*/synthesis-*.md` is left out of searches and tag
  listings for every role. It stays readable by path. The decision note
  next to it and the briefs stay searchable, so what was decided before
  can still be found.

Running HX on a cheaper model was considered and left for later: it is the
change most likely to cost quality, and the squad ignores `Role.model`
today. Giving the PMs one shared HX consultation per round was dropped: it
changes the committee's shape (ADR 0013) to save what excerpts make cheap.

## Consequences

- On the vault of that run, the same searches return about 3,000
  characters instead of about 95,000.
- An agent that needs a note's content makes one more round trip: search,
  read, answer. Each trip is much smaller, so the total is expected to go
  down, but a run that reads many notes pays for each read.
- An agent can answer from an excerpt without reading the note. The source
  validators check that a cited note exists, not that it was read. If
  answers get shallow, the next step is to require by code that a cited
  note was read in the same run.
- Matches past the eighth are not returned and the tool does not say how
  many there were: the caller narrows the query.
- Not a breaking change for callers: a tool's return shape is not public
  API, and `Note` and `KnowledgeBase` are unchanged.
- A brief from an earlier request is searchable. That is intended, since a
  brief is a decision, but it means a request repeated on the same vault
  finds the earlier answer.
