# Scoring reference

## The three components

| Component | Question it answers | 1 | 10 |
| --- | --- | --- | --- |
| Impact | How much does this move the target metric if it works? | Barely measurable | Could double the metric |
| Confidence | How sure are we it will work, given the evidence? | Pure guess, no evidence | Backed by direct evidence for this exact change |
| Effort | How much work does it take? | Days | Months |

Confidence should track HX's findings directly: a hypothesis built only on
`assumption` or `gap` findings caps confidence around 3-4; one backed by
`evidence` findings can go higher.

## Priority score

```
priority = (impact * confidence) / effort
```

Effort divides the score, so an expensive bet needs proportionally higher
impact or confidence to rank above a cheap one — a large effort score should
never be read as a tiebreaker on its own.

## Reporting

For each bet, report:

```
<bet name>: priority <score> (impact <n>, confidence <n>, effort <n>)
```

Sort descending by score. Ties break toward higher confidence, since an
overconfident low-confidence bet is the more expensive mistake to make.
