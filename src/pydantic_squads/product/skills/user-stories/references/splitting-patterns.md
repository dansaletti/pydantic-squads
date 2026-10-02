# Splitting patterns

Split a story so that every piece still delivers something a user can see
or do. Try the patterns roughly in this order; the first one that produces
pieces of real value wins.

| Pattern | Split along | Example (a daily-journal app) |
|---|---|---|
| **Workflow steps** | The steps a user goes through, delivering the first and last step before the middle ones | "Answer today's question" first; "edit a past answer" later |
| **Business rule variations** | Each rule the story enforces becomes its own story | "Question matches the baby's age" vs. "a missed day resumes where it stopped" |
| **Happy path first** | The main path, then each failure or edge case | "Save a text answer" vs. "save while offline" |
| **Data variations** | Kinds of input the story handles | "Answer with text" vs. "answer with a photo" |
| **Data entry methods** | Simple input before rich input | Plain text field before a formatted editor |
| **Operations** | Create, read, update, delete as separate stories | "Add a milestone" vs. "delete a milestone" |
| **Simple / complex** | The simplest version, then the variations that make it complex | "Monthly throwback with one memory" vs. "tie-break by photo" |
| **Defer performance** | Make it work, then make it fast or scale | "Timeline loads" vs. "timeline loads in under a second with a year of entries" |

## When nothing splits cleanly

If the story is too big because nobody knows how it should work, the
missing piece is a decision, not a story. Send the bet back with the
question rather than inventing an answer.

## Anti-patterns

- **By technical layer** (frontend story + backend story): neither half is
  independently valuable to a user.
- **By team or component**: same problem, different name.
- **"Part 1 / Part 2"**: a split with no axis is just a smaller estimate of
  the same unclear work.
- **A story per acceptance criterion**: criteria describe one story's
  behavior; they are not stories of their own unless each is valuable alone.
