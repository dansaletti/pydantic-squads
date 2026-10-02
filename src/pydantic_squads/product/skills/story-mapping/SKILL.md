---
name: story-mapping
description: Lay a bet's stories out along the user's journey to find gaps and choose the thinnest end-to-end first slice. Use when a bet spans several steps of a flow, or when the backlog has more than a handful of stories and their order matters.
---

# Story Mapping

## When to Use This Skill

Use this skill before finalizing a `Backlog` whose bet covers more than
one step of what a user does — a flow, a journey, a multi-screen feature.
A flat list of stories hides gaps and makes it easy to build the details
of one step before any step works end to end. A story map shows both.

## Instructions

1. Write the **backbone**: the activities the user goes through for this
   bet, left to right in the order they happen. Use the user's words
   ("receive the question", "answer it", "see it in the timeline"), not
   screens or components. See `references/story-map.md` for the layout.
2. Under each activity, list the **steps**, then the stories that
   implement each step, most essential at the top.
3. Look for **gaps**: an activity with no story means the user gets stuck
   there. If the bet's scope covers that activity, add the story; if the
   bet never said what happens there, that is a `SendBack`.
4. Draw the **first slice**: the thinnest set of stories that lets a user
   go through every activity end to end, even crudely. That slice comes
   first in the `Backlog`, in backbone order.
5. Order the remaining stories by slice, then by backbone order within a
   slice. Stories below what the bet's scope covers are not added — the
   map is a thinking tool, and only in-scope stories become the `Backlog`.
6. Each story that comes out of the map still follows the `user-stories`
   skill: its title format, Given/When/Then criteria and `needs_design`.
