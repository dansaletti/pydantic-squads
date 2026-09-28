# 0001. The core depends only on pydantic

Status: accepted

## Context

Roles, squads and contracts describe a squad. Running agents is a separate concern.

## Decision

`role`, `squad`, `policies`, `prompt` and future `contracts` import only `pydantic`. Anything that needs `pydantic_ai` lives in an optional module behind an extra.

## Consequences

Definitions are testable without an API key or network, and a squad definition is portable if a user runs it on another framework.
