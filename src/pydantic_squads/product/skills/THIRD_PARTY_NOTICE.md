# Third-party skills

## marketingskills (MIT)

The marketing skills of the Growth PM, the Marketing PM and Social Media come from
[coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills),
commit `0baf720ab0c3793aa46beb4b7a7d331d51bf7a00`:

`ab-testing`, `analytics`, `churn-prevention`, `customer-research`, `launch`,
`marketing-psychology`, `onboarding`, `paywalls`, `pricing`,
`product-marketing`, `referrals`, `social`.

Only `SKILL.md` and `references/` were copied (not `evals/`). They were
adapted to this runtime: references to `.agents/product-marketing.md` point
to the squad's product context and the knowledge-base note
`docs/product-marketing.md`, and links to the upstream `tools/` registry
were removed, and `product-marketing` hands its draft over when the role
running it cannot write notes.

```
MIT License

Copyright (c) 2025 Corey Haines

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## impeccable (Apache-2.0)

The Designer's `impeccable` skill is adapted from
[pbakaus/impeccable](https://github.com/pbakaus/impeccable), commit
`508d7e8955de3b3caf2d8676e85206723d41a887`, licensed under the Apache
License 2.0 (full text in `impeccable/LICENSE`).

Changes made here:

- `SKILL.md` was rewritten for the Designer's Backlog → Prototype flow; the
  upstream launcher, live-browser, hooks, pin and doctor workflows were
  dropped, along with the `scripts/` folder.
- Only these references were kept, from `reference/` into `references/`:
  adapt, animate, audit, bolder, clarify, colorize, craft-floor, delight,
  distill, extract, harden, layout, onboard, operate, polish, quieter,
  shape, typeset.
- In those references: launcher commands and detector steps became manual
  checks of the HTML and CSS; `DESIGN.md` became the `design-system/` notes;
  identity changes route to a founder question instead of `new-work.md`;
  native-platform branches and live-mode parameter contracts were removed;
  `/impeccable <command>` hand-offs point to the matching reference file.

Upstream NOTICE: Impeccable's `ios.md` and `android.md` derive from ehmo's
`platform-design-skills` (MIT); neither file is included here.
