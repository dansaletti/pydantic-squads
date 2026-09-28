# 0003. Ship a ready-made product squad

Status: accepted

## Context

Every team adopting `pydantic-squads` was rewriting the same Growth PM / HX /
Product Owner roles, the same hand-off contracts and the same send-back loop
by hand. That is not squad-specific opinion to keep out of the library — it is
the reference workflow the library exists to demonstrate, and re-deriving it
in every consuming project produced drift, not a real use case.

## Decision

`pydantic_squads.product` ships a ready-made product squad (Growth PM, HX
researcher, Product Owner) with typed hand-off contracts (`Finding`,
`HXAnswer`, `Bet`, `Backlog`, `SendBack`), a `KnowledgeBase` protocol, and,
behind the optional `ai` extra, a Pydantic AI assembly (`ProductSquad`).
Consuming projects supply only a `KnowledgeBase` (a notes vault) and product
context; they do not redefine roles or contracts.

This narrows the "no product-specific content" rule in `CLAUDE.md` to one
exception: the shipped product squad is the library's reference
implementation, not a product built on top of it. Anything specific to a
single company's product — their bets, their notes, their metrics — still
stays out of this repo.

## Consequences

- `pydantic_squads.product.contracts`, `.roles` and `.squad` stay
  dependency-free (ADR 0001), so they are testable and portable without an
  LLM, same as the rest of the core.
- `pydantic_squads.product.knowledge` (the markdown/Obsidian adapter) is also
  pydantic-only; only `pydantic_squads.product.assembly` requires
  `pydantic_ai` and the `ai` extra.
- The library is now opinionated about product work specifically, while
  staying framework-agnostic for everything else: a support squad or a
  payments squad is still built by hand with `Role` and `Squad`.
