---
name: evidence-classification
description: Classify a claim about users as evidence, assumption or gap, with the right sources for each. Use whenever answering a question about users or writing a Finding.
---

# Evidence Classification

## When to Use This Skill

Use this skill every time a claim about users needs a `kind` before it
becomes a `Finding`: evidence, assumption, or gap. Getting this wrong either
overstates what the team actually knows, or throws away a real signal by
mislabeling it a guess.

## Instructions

1. Read `references/criteria.md` before classifying anything you have not
   classified in this conversation yet.
2. For each claim, decide:
   - **evidence** — directly observed: an interview quote, a support ticket,
     usage data, a test result. Requires at least one source.
   - **assumption** — written by the team (a spec, a roadmap doc, a
     stakeholder opinion) but not yet confirmed by user behavior. Requires
     at least one source (the document it came from).
   - **gap** — the knowledge base has nothing on this. No source, because
     there is nothing to cite.
3. Never invent a source to make a claim look like evidence. If the only
   thing backing a claim is "the team believes this," it is an assumption,
   not evidence, no matter how confident the team is.
4. When in doubt between evidence and assumption, prefer assumption — a
   demoted claim can be promoted later when real evidence appears; an
   inflated one misleads the Growth PM's confidence score.
