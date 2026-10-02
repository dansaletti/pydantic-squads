# INVEST checklist

A story is ready when it is:

- **Independent** — it does not require another unbuilt story to be
  testable on its own.
- **Negotiable** — it describes an outcome, not a fixed implementation; how
  to build it is still open.
- **Valuable** — it is worth something on its own to the user or the
  metric the bet targets, not just a technical step.
- **Estimable** — the team can size it without more information.
- **Small** — it fits in a single iteration; if it doesn't, split it again.
- **Testable** — its acceptance criteria can be checked by using the
  product, not by reading the code.

A story that fails **Small** or **Independent** gets split — see
`splitting-patterns.md`. A story that fails **Valuable** usually came from
splitting by technical layer; merge it back and split along a different
axis. A story that fails **Estimable** or **Testable** because the bet
never said what should happen is a `SendBack`, not a story.
