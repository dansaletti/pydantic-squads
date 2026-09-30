# One HTML file, many screens

The prototype is a single self-contained `.html` file: anyone can open it
from disk, offline, with nothing else installed.

## Rules

- No external URLs: no CDN scripts, web fonts, remote images or
  stylesheets. Inline all CSS in one `<style>` and all JS in one `<script>`.
  Use system font stacks and inline SVG for icons.
- `<meta name="viewport" content="width=device-width, initial-scale=1">`.
- Design-system tokens become CSS custom properties on `:root`, so every
  screen uses the same values.

## Structure

Each screen is a `<section>` with an `id`; only the one matching the URL
hash is visible. Links between screens are plain `<a href="#screen-id">`,
so the browser's back button works.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Prototype</title>
  <style>
    :root { --color-primary: #1f5eff; --space-2: 8px; --radius-1: 8px; }
    section { display: none; }
    section:target, section.default:not(:has(~ section:target)) { display: block; }
  </style>
</head>
<body>
  <section id="signup" class="default">
    <h1>Create your account</h1>
    <a href="#signup-error">Submit (error state)</a>
  </section>
  <section id="signup-error">
    <h1>Create your account</h1>
    <p role="alert">That email is already registered.</p>
    <a href="#signup">Back</a>
  </section>
</body>
</html>
```

- Show each state as its own screen (`#signup-empty`, `#signup-loading`,
  `#signup-error`) or behind a small state switcher on the screen, so a
  reviewer can reach every state without real data.
- Start with an index screen listing every screen and state, for review.
- Keep scripts to navigation and state switching; no business logic.
