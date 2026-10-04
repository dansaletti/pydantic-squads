---
name: prototyping
description: Turn stories that need design into a navigable, mobile-first, single-file HTML prototype on top of a design system, and ask the founder what only they can decide. Use when turning a Backlog into a Prototype.
---

# Prototyping

## When to Use This Skill

Use this skill when turning a `Backlog` into a `Prototype`: it governs which
screens to draw, how to build them into one navigable HTML file, how to use
and grow the design system, and when to stop and ask the founder instead of
deciding.

## Instructions

1. Read the backlog and list the stories with `needs_design: true`. Every one
   of them must appear, by exact title, in at least one `Screen.stories`.
   Never cite a story title that is not in the backlog, and never draw
   screens for backend-only stories.
2. Read `design-system/` before drawing anything. Use its tokens and
   components. When something is missing, add it to
   `design_system_changes` as a `ComponentProposal` (name, reason, spec)
   instead of inventing a one-off style.
3. If `design-system/` is empty, propose an initial one: tokens for color,
   typography, spacing and radius, plus base components (button, input,
   list item, card, navigation, feedback). Base it on what HX knows about
   the users. Writing to `design-system/**` needs the founder's approval, so
   write it once, as a small coherent set of notes.
4. Consult HX before claiming anything about users. A finding HX classifies
   as a `gap` becomes a `FounderQuestion` with `origin: "hx_gap"` and the
   question you put to HX in `hx_question`.
5. Positioning, tone and brand are the founder's call. Never settle them
   yourself: ask a `FounderQuestion` with `origin: "positioning"`, and
   design with your `suggested_default` in the meantime. See
   `references/founder-questions.md`.
6. Design mobile-first (`references/mobile-first.md`) and draw every state
   each screen can be in: default, empty, loading, error, and success where
   it applies. List them in `Screen.states`.
7. Check accessibility (`references/accessibility.md`) and usability
   (`references/usability-heuristics.md`) before delivering. For the craft
   of each screen and the final quality pass, load the `impeccable` skill.
8. Build the prototype as one self-contained HTML file in the output
   directory you are given, following `references/single-file-prototype.md`:
   inline CSS and JS, no external URLs, navigable between screens. Set
   `html_path` to where you wrote it.
9. If a story is too ambiguous to become a screen — you would have to
   invent what it does, not just how it looks — that is a `SendBack` to the
   Product Owner, not a guess.
