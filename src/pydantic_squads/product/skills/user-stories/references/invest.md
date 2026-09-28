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

## Splitting patterns

When a story fails "small" or "independent", split along one of these axes
rather than by technical layer:

- **By workflow step** — the first screen a user sees vs. the confirmation
  they see after.
- **By variation** — the happy path vs. a specific edge case (e.g. an
  expired session).
- **By data variation** — one record vs. a paginated list of them.

Avoid splitting by technical layer (frontend story + backend story): neither
half is independently valuable to a user, which fails "Valuable" on its own.

## Acceptance criteria template

```
Given <a starting state>
When <the user does something>
Then <an observable, checkable outcome>
```

Each criterion should name something a person can go verify by using the
product — "the confirmation page shows the order total" is testable;
"the confirmation logic is correct" is not.
