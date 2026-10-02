# Story map layout

```
Backbone (activities, in order) →
  Receive question  |  Answer it            |  Revisit it
  ------------------+-----------------------+------------------------
Steps
  open notification |  write or add photo   |  scroll the timeline
                    |  save                 |  open one entry
  ------------------+-----------------------+------------------------
Slice 1 (walking skeleton)
  see today's       |  save a text answer   |  see the answer in the
  question on open  |                       |  timeline with the date
  ------------------+-----------------------+------------------------
Slice 2
  question matches  |  answer with a photo  |  see the baby's age on
  the baby's age    |                       |  each entry
  ------------------+-----------------------+------------------------
Later (outside this bet — not in the Backlog)
  push at bedtime   |  voice answer         |  monthly throwback
```

## Reading the map

- **Horizontal** is time: the order a user experiences the activities.
- **Vertical** is priority: higher rows are more essential.
- **A slice** is a horizontal cut across every activity. Slice 1 is the
  walking skeleton — crude, but usable end to end. It ships before any
  activity gets polished.

## Checks before turning the map into a Backlog

- Every activity in the backbone has at least one story in slice 1.
- No story in slice 1 depends on a story in a later slice.
- Nothing in the map contradicts the bet's `out_of_scope`.
- The "Later" row exists only on the map; none of it becomes a story.
