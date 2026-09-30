# Accessibility checklist

Accessibility is part of the design, not a later pass.

## Contrast

- Text contrast at least 4.5:1 against its background (3:1 for text 24px
  and up, or 19px bold and up).
- Icons, input borders and focus indicators at least 3:1.
- Never use color alone to carry meaning: pair it with text or an icon
  (e.g. an error is red *and* says "Error").

## Touch and pointer targets

- At least 44×44px, with space between adjacent targets.
- The whole row or card is tappable when it acts as one item.

## Screen readers and semantics

- Use real elements: `<button>` for actions, `<a>` for navigation, `<label>`
  tied to every input, headings (`<h1>`–`<h3>`) in order.
- One `<h1>` per screen, describing it.
- Images that carry meaning have `alt` text; decorative ones have `alt=""`.
- Status changes (saved, error, loading done) are announced with an
  `aria-live` region.
- Every screen is fully usable with a keyboard, in a logical focus order,
  with a visible focus indicator.

## Motion and text

- Respect `prefers-reduced-motion`.
- Layout survives 200% text zoom without cutting off content.
