# 0002. Invariants versus policies

Status: accepted

## Context

Some composition rules are true for every squad; others reflect how a particular team wants to work.

## Decision

Invariants (unique ids, known references, reserved `human` id, no delete permission) are enforced by `Squad` and cannot be turned off. Opinionated rules (a single conversational role; only it talks to the human) are policies: plain callables, passed through `Squad(policies=...)`, with sensible defaults.

## Consequences

The library stays opinionated out of the box without locking users into our way of working.
