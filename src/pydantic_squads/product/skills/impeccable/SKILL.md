---
name: impeccable
description: Raise a prototype's design craft — hierarchy, layout, typography, color, motion, UX copy, empty and error states, onboarding, responsiveness and accessibility — and audit it before delivery. Use while building a Prototype, after the prototyping skill has set what to draw, and as the quality pass before delivering it.
license: Apache-2.0
---

<!-- Adapted from pbakaus/impeccable (Apache-2.0); see ../THIRD_PARTY_NOTICE.md. -->

# Impeccable

## When to Use This Skill

The `prototyping` skill decides *what* to draw: which screens, which
states, which stories they cover, when to ask the founder. This skill
decides *how well* it is drawn. Use it while building each screen and once
more, as a quality pass, before delivering the `Prototype`.

## How to design

- **The design system and the founder win.** Honor the tokens, components,
  fonts and palette in `design-system/` even when your own taste points
  elsewhere. A change of identity — new palette, new fonts, a new visual
  world — is a brand decision: ask the founder with a `FounderQuestion`
  (`origin: "positioning"`) and propose it as a `ComponentProposal`; never
  apply it on your own.
- **Refinement preserves.** A screen built on an existing design keeps its
  identity, behavior and copy outside the story's scope. Ask before
  replacing factual copy or adding claims.
- **Design for the task.** The prototype is app UI: the user is in the
  middle of something. Scanability, consistency, platform expectations and
  the real usage scene outrank expression; the brand lives in precise
  details. See `references/operate.md`.
- **Go all the way on quality, not on volume.** Every screen is complete,
  in every state it can be in. Inspect in bounded passes: build, review once
  against the floor, fix everything in one batch, review once more, stop.
- **You cannot render the page.** Inspect by reading the HTML and CSS you
  wrote: computed sizes, contrast pairs, spacing values, states. Do not
  claim to have seen a screenshot.

## Instructions

1. Before drawing, use `references/shape.md` to settle what each screen
   must make obvious, for whom, and in which situation.
2. Build each screen with the reference that matches the work:

   | Need | Reference |
   |---|---|
   | Spacing, rhythm, visual hierarchy | `references/layout.md` |
   | Type scale, pairing, hierarchy | `references/typeset.md` |
   | Color with purpose, contrast | `references/colorize.md` |
   | Motion and transitions | `references/animate.md` |
   | Labels, buttons, errors, empty-state copy | `references/clarify.md` |
   | First run, empty states, activation | `references/onboard.md` |
   | Error, loading, offline, long-content, i18n states | `references/harden.md` |
   | Small screens, touch, safe areas | `references/adapt.md` |
   | Personality and memorable touches | `references/delight.md` |
   | A screen too busy or too complex | `references/distill.md`, `references/quieter.md` |
   | A screen too timid for its role | `references/bolder.md` |
   | A pattern worth adding to the design system | `references/extract.md` |

3. Read `references/craft-floor.md` immediately before writing the HTML.
   It is the quality floor: its bans and checks apply to every screen.
4. Before delivering, run `references/audit.md` against the prototype
   (accessibility, responsiveness, theming, implementation integrity), fix
   what it finds, then finish with `references/polish.md`.
5. When a reference tells you to change the design system, express it as a
   `ComponentProposal`, not as a one-off style in the prototype.
6. Anything these references suggest that changes scope or stories is out
   of bounds for the Designer: leave it out, or send it back.
