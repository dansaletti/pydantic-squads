# 0008. Run the squad on a local Claude Code login

Status: accepted

## Context

Every `ProductSquad` call is several model requests (Growth PM, a nested
HX consultation, retries). Billed to an API key, exploring a product with
the squad costs money on every conversation, even for a founder who
already pays for a Claude subscription and has Claude Code installed.

Claude Code can run one-shot and non-interactively (`claude -p`), with its
own login, and return JSON. But it runs its own agent loop and its own
tools, while the squad's guarantees (path permissions, approvals through
`DeferredToolRequests`, output validators such as the Designer's coverage
gate) all live in Pydantic AI tools and validators.

Anthropic does not allow third-party products to offer claude.ai login or
its rate limits to their users. A library can let *its own user* run it on
their own login, locally; it cannot make that login part of a product.

## Decision

- **Claude Code is a model, not an agent runtime.** `ClaudeCodeModel`
  (`pydantic_squads.product.claude_code`, `ai` extra) implements Pydantic
  AI's `Model`: each model request becomes one `claude -p` call with every
  native tool and MCP server turned off (`--tools ""`,
  `--strict-mcp-config`), no session persistence, the agent's system
  prompt in a temp file (`--system-prompt-file`) and a JSON envelope
  schema (`--json-schema`): `{"text", "tool_calls": [{"name",
  "arguments"}]}`. The conversation goes in on stdin as a plain-text
  transcript. Tool calls come back as `ToolCallPart`s and run in Python,
  inside Pydantic AI, exactly as with any other model, so nothing in the
  squad changes: permissions, approvals, validators and traces all work.
- **The login, not an API key.** By default the subprocess runs without
  `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`, so Claude Code uses the
  logged-in account. `use_subscription=False` keeps them.
- **Isolated by default.** The CLI runs in a fresh empty directory per
  call, so a project's `CLAUDE.md`, hooks or `.mcp.json` don't leak into
  the squad. `cwd=` overrides it. `--bare` is not used: it skips the
  OAuth login.
- **Selected by a string.** `ProductSquad(model="claude-code")` or
  `model="claude-code:<model>"` (`resolve_model()`), so an app can choose
  the backend from configuration (`model=os.environ["SQUAD_MODEL"]`)
  without importing anything else. Any other model passes through
  unchanged.
- **One protocol correction.** When an agent only accepts a tool call (a
  structured output such as a `Bet`) and the answer has none, the request
  is repeated once (`protocol_retries`) with a correction before Pydantic
  AI's own output retries are spent.
- **A second correction: "function unavailable".** When an agent accepts
  text but the answer says one of the offered functions is unavailable
  (the model reached for a native Claude Code tool instead of
  `tool_calls`), the request is repeated (`protocol_retries`) with a
  correction, and an answer that still says so raises `ClaudeCodeError`.
  Otherwise the agent answers from the prompt alone, without the
  knowledge base, and the reply looks fine: nothing signals the failure.
- **The protocol stays at the end of the system prompt.** Moving it to
  the start was measured with the real CLI (Sonnet, the Growth PM with
  its seven tools, six first messages each): with the protocol last the
  agent called a tool in 6 of 6, with it first (plus a one-line reminder
  at the end) in 1 of 6. A small sample, but not a change to retry
  without measuring.
- **Documented as local, personal use**, never as a way to ship the squad
  inside a product.

## Consequences

- No extra dependency: only `asyncio` subprocesses. Tests replace the
  runner and never call the CLI (except to run a trivial Python process
  for the default runner).
- Slower than the API: every request starts a CLI process (seconds), and
  Claude Code adds its own context to each call.
- Subject to the subscription's usage limits, which a long squad session
  can hit.
- Usage comes from the CLI's own result: `input_tokens` is the whole
  prompt, cached tokens included (the CLI reports those apart, which
  leaves its bare `input_tokens` at a handful), and cost is its
  `total_cost_usd`. That cost is an estimate at API list prices, a way
  to compare cycles, not something a subscription is charged.
- Tool calling is prompted, not native: strong models (Sonnet, Opus)
  follow the protocol reliably, small ones (Haiku) sometimes don't.
- No streaming and no images in user prompts (they are replaced by a
  placeholder in the transcript).
