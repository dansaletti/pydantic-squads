# Mobile-first checklist

Design for a ~360px-wide viewport first, then let the layout grow.

- One primary action per screen, reachable with a thumb (bottom half of the
  screen).
- Single-column layout; no horizontal scrolling at 360px.
- Body text at least 16px; line length comfortable at every width.
- Touch targets at least 44×44px with at least 8px between them.
- Forms: one field per row, the right input type (`email`, `tel`,
  `number`), labels above fields, and no more fields than the story needs.
- Navigation that fits the screen: a bottom bar or a short list, not a
  desktop menu squeezed down.
- Content first, chrome second: headers stay short so the task is visible
  without scrolling.
- Wider screens get more whitespace and, where it helps, a second column —
  never a different flow.
- Assume a slow network: every screen that loads data has a loading state
  and an error state with a retry.
