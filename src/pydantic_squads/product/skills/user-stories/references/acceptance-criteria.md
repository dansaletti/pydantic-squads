# Acceptance criteria

Write each criterion as one scenario:

```
Given <a starting state the tester can set up>
When <one action the user takes>
Then <an outcome the tester can observe in the product>
```

Use `And` to add a condition or outcome to the same scenario, never to
chain a second action.

## Rules

- **One behavior per criterion.** Two `When`s mean two criteria.
- **Observable outcomes.** "Then the entry appears at the top of the
  timeline with today's date" is testable; "then the entry is saved
  correctly" is not.
- **Concrete states.** "Given a baby who is 3 months old" beats "given a
  user with data".
- **User language, not implementation.** No table names, endpoints or
  component names; the Designer and the tester both read these.
- **Cover what the scope implies.** The main path, each failure path
  (offline, invalid input, nothing to show) and each empty state the bet's
  scope covers — and nothing the scope excludes.
- **Quality constraints only with a number.** "Loads in under 2 seconds on
  a 4G connection" is a criterion; "is fast" is not.

## Example

Story: As a mother of a newborn, I want to answer today's question with a
photo, so that the memory keeps what words can't.

- Given today's question is open, When I attach a photo and save, Then the
  answer appears in the timeline with the photo and today's date
- Given today's question is open, When I save without text or photo, Then I
  see that an answer needs text or a photo, and nothing is saved
- Given I am offline, When I save a photo answer, Then I see it is waiting
  to sync, And it appears in the timeline once I am back online
