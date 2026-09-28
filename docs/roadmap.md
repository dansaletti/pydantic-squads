# Roadmap

Non-binding. Features are promoted to the core only when a real squad needs
them. The reference squad is `pydantic_squads.product` (see ADR 0003); the
items below are being built through it, in phases:

1. **Hand-off contracts**: typed Pydantic models for what flows between
   roles — `pydantic_squads.product.contracts` (`Finding`, `HXAnswer`,
   `Bet`, `Backlog`, `SendBack`).
2. **Knowledge base**: a protocol for reading and writing notes, with a
   markdown/Obsidian adapter, path containment and no delete operation —
   `pydantic_squads.product.knowledge`.
3. **Assembly**: build Pydantic AI `Agent`s from the product roles,
   contracts and knowledge-base tools, behind the optional `ai` extra —
   `pydantic_squads.product.assembly`.
4. **Flow helpers**: a human checkpoint before a bet reaches the Product
   Owner, and a bounded send-back loop back to the Growth PM —
   `ProductSquad.close_bet()` in the assembly module.
