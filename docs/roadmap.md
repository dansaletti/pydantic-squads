# Roadmap

Non-binding. Features are promoted to the core only when a real squad needs them.

1. **Hand-off contracts**: typed Pydantic models for what flows between roles; `Role.delivers` points to a contract type.
2. **Assembly**: build a Pydantic AI `Agent` from a `Role` + output contract + tools (optional `pydantic-ai` extra).
3. **Knowledge base**: a protocol for reading and writing notes, with a markdown/Obsidian adapter, path validation and approval via Pydantic AI deferred tools.
4. **Flow helpers**: human checkpoint between roles, bounded send-back loops.
