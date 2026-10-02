---
name: user-stories
description: Split an approved bet into small, testable user stories with Given/When/Then acceptance criteria. Use when turning a Bet into a Backlog, or when a story is too big to build or test on its own.
---

# User Stories

## When to Use This Skill

Use this skill when turning a founder-approved bet into a `Backlog`: it
governs how to split the bet into stories, how to phrase each one, and how
to write acceptance criteria that are actually testable.

## Instructions

1. Split the bet's scope into the smallest stories that each deliver
   something independently checkable. Check every story against
   `references/invest.md`; when one is too big or depends on another,
   split it with a pattern from `references/splitting-patterns.md`.
2. Write each story title in the format "As a <who>, I want <what>, so
   that <why>". The *who* is a real user from the bet, never "the system"
   or "the developer"; the *what* is something the user does or sees, not
   a technical task; the *why* ties back to the outcome the bet's metric
   measures. Keep it to one sentence.
3. Write acceptance criteria in Given/When/Then form, one criterion per
   rule or path, following `references/acceptance-criteria.md`. Each one
   must be something a person can verify true or false by using the
   product, not a description of the implementation. Cover the main path
   and every failure or empty state the bet's scope implies.
4. Set `needs_design` on every story. It is `true` when the story changes
   what a user sees or does (a new screen, a new state, a changed flow or
   message) and `false` when it is backend-only (storage, jobs,
   integrations with no visible change). The Designer prototypes every
   `true` story and nothing else, so when in doubt, mark it `true`.
5. Anything the bet's `out_of_scope` excludes must not turn into a story,
   even a small one.
6. If the bet is too ambiguous to split — the scope is unclear, or a story
   would require inventing requirements the bet never stated — that is a
   `SendBack`, not a guess.
