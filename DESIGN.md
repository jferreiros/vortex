---
version: 1
name: vortex-design-system
description: |
  The Vortex front ends read like a Markdown README rendered with care. Paper-white
  canvas, one black pill per action, hairline cards, system fonts, code as a first-class
  element, and the Vortex mark as the only ornament. No gradient, no shadow, no brand
  colour. Status is the only colour on the page, and it borrows the three macOS
  terminal traffic lights. One dark surface per page says "look here" to the jury.
  The system is the documentation, and the documentation is the system.

colors:
  primary: "#000000"
  on-primary: "#ffffff"
  ink: "#000000"
  ink-deep: "#090909"
  charcoal: "#525252"
  body: "#737373"
  mute: "#a3a3a3"
  canvas: "#ffffff"
  surface-soft: "#fafafa"
  surface-card: "#ffffff"
  hairline: "#e5e5e5"
  hairline-strong: "#d4d4d4"
  on-dark: "#ffffff"
  on-dark-mute: "rgba(255,255,255,0.7)"
  surface-dark: "#171717"
  focus-ring: "rgba(59,130,246,0.5)"
  link: "#000000"
  link-mute: "#737373"
  terminal-red: "#ff5f56"
  terminal-yellow: "#ffbd2e"
  terminal-green: "#27c93f"

typography:
  display-xl:
    fontFamily: SF Pro Rounded
    fontSize: 36px
    fontWeight: 500
    lineHeight: 1.11
    letterSpacing: 0
  display-lg:
    fontFamily: SF Pro Rounded
    fontSize: 30px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0
  heading-lg:
    fontFamily: SF Pro Rounded
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.33
    letterSpacing: 0
  heading-md:
    fontFamily: ui-sans-serif
    fontSize: 20px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0
  heading-sm:
    fontFamily: ui-sans-serif
    fontSize: 18px
    fontWeight: 500
    lineHeight: 1.56
    letterSpacing: 0
  body-md:
    fontFamily: ui-sans-serif
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  body-strong:
    fontFamily: ui-sans-serif
    fontSize: 16px
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: 0
  body-sm:
    fontFamily: ui-sans-serif
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.43
    letterSpacing: 0
  body-sm-strong:
    fontFamily: ui-sans-serif
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.43
    letterSpacing: 0
  caption-sm:
    fontFamily: ui-sans-serif
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.33
    letterSpacing: 0
  code-md:
    fontFamily: ui-monospace
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  code-sm:
    fontFamily: ui-monospace
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.43
    letterSpacing: 0
  button-md:
    fontFamily: ui-sans-serif
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1
    letterSpacing: 0

rounded:
  none: 0px
  sm: 6px
  md: 8px
  lg: 12px
  full: 9999px

spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  section: 88px

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button-md}"
    rounded: "{rounded.full}"
    padding: 8px 20px
    height: 36px
  button-primary-active:
    backgroundColor: "{colors.ink-deep}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button-md}"
    rounded: "{rounded.full}"
  button-secondary:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.button-md}"
    rounded: "{rounded.full}"
    padding: 8px 20px
    height: 36px
  button-pill-on-dark:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.button-md}"
    rounded: "{rounded.full}"
    padding: 8px 20px
  button-disabled:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.mute}"
    rounded: "{rounded.full}"
  search-pill:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.full}"
    padding: 8px 16px
    height: 36px
  search-pill-focused:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.full}"
  text-input:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.full}"
    padding: 8px 16px
    height: 40px
  text-input-focused:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.full}"
  install-snippet:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.code-md}"
    rounded: "{rounded.full}"
    padding: 12px 20px
    height: 48px
  command-tag:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.code-sm}"
    rounded: "{rounded.full}"
    padding: 6px 12px
  terminal-card:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.code-sm}"
    rounded: "{rounded.lg}"
    padding: 16px
  terminal-traffic-lights:
    rounded: "{rounded.full}"
    size: 12px
  card:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.lg}"
    padding: 32px
  card-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
    typography: "{typography.body-md}"
    rounded: "{rounded.lg}"
    padding: 32px
  feature-bullet:
    textColor: "{colors.charcoal}"
    typography: "{typography.body-sm}"
  faq-row:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.none}"
    padding: 16px 0px
  link-inline:
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
  link-mute:
    textColor: "{colors.body}"
    typography: "{typography.body-sm}"
  primary-nav:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm-strong}"
    rounded: "{rounded.none}"
    height: 56px
  footer-section:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.body}"
    typography: "{typography.caption-sm}"
    rounded: "{rounded.none}"
    padding: 32px 24px
  cta-strip-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
    typography: "{typography.heading-lg}"
    rounded: "{rounded.lg}"
    padding: 24px 32px
  status-dot:
    rounded: "{rounded.full}"
    size: 8px
  pill:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm-strong}"
    rounded: "{rounded.full}"
    padding: 0px 12px
    height: 28px
---

# Vortex design system

This file is the source of truth for every screen Vortex shows to a human: the
jury wall, the ops board, the docs pages, the mic test page and the evals report.
`vortex/observability/design.css` turns the tokens above into CSS. Every front
end loads that file first and adds only what its layout needs.

Read this file before you touch any HTML, CSS or NiceGUI code. When a screen
looks different from the others, it is wrong, not different.

## Where the pieces live

| Surface | Who sees it | Code | How it loads the tokens |
| --- | --- | --- | --- |
| Jury wall, `/wall` | the jury, on a projector | `vortex/observability/live.py`, `board.css` | `ui.add_css(design.css)` then `board.css` |
| Ops board, `/` | the team | same | same |
| Mic test, `/mic` on the line server | the team | `vortex/line/mic.html` | `<link href="/design.css">`, served by `server.py` |
| Evals report | the team, CI artifact | `evals/common/report.py` | inlines `design.css` at render time |
| Plan and task board | the team, GitHub Pages | `docs/index.html`, `docs/tasks.html` | `<link href="design.css">`, the synced copy |

`docs/design.css` is a copy. GitHub Pages serves only `docs/`, so the copy is
unavoidable. `make design-sync` refreshes it. `tests/test_design.py` fails
when the two files differ, so CI catches a stale copy.

## How to change something

1. Change the token in the YAML front matter above.
2. Change the same token in `vortex/observability/design.css`.
3. Run `make design-sync`.
4. Run `make test`.
5. Open the wall, the ops board and `docs/index.html` and look at all three.

Do not add a colour, a font or a radius to one page only. If a page needs a
value the tokens do not have, add the token here first. Most of the time the
existing pill, hairline card and terminal card already cover the case.

## Overview

The page is a README. A `{typography.display-xl}` headline sits at the top of
a 720px reading column. Under it comes prose in `{colors.body}` grey, then
lists, then code inside a `{component.install-snippet}` pill or a
`{component.terminal-card}`. Sections breathe with `{spacing.section}` of
white air and nothing else separates them.

Every interactive element is a pill (`{rounded.full}`). Cards are the only
exception at `{rounded.lg}`. There are no shadows, no gradients and no
photography. The Vortex mark (`docs/vortex-mark.png`) is the one illustration.

**Key characteristics**

- Paper-white `{colors.canvas}` from edge to edge. No surface alternation.
- One black `{component.button-primary}` per fold. It is the only CTA style.
- Pills for everything you can click. `{rounded.lg}` for the few cards.
- Code is a first-class component, never an afterthought.
- Exactly one `{colors.surface-dark}` surface per page. It is the "look here".
- Status is colour and colour is status. Nothing else on the page has a hue.

## Colors

### Brand and accent

- **Primary** (`{colors.primary}`, `#000000`) is the brand. Every primary
  action, every solid icon, every nav link.
- **Ink deep** (`{colors.ink-deep}`, `#090909`) is the pressed state of a
  primary pill. One notch below pure black.

### Surface

- **Canvas** (`{colors.canvas}`) is the page. Almost every surface.
- **Surface soft** (`{colors.surface-soft}`) fills the install pill, the
  search pill, the command tag and the agent's speech bubble.
- **Surface dark** (`{colors.surface-dark}`) is the single inverted surface
  per page. On the wall it is the verdict card. On the docs it is the one
  block the reader must not miss.
- **Hairline** (`{colors.hairline}`) draws every 1px border and divider.
- **Hairline strong** (`{colors.hairline-strong}`) draws the secondary
  button border and the neutral pill border.

### Text

- **Ink** (`{colors.ink}`) for headlines, names, values, nav links.
- **Charcoal** (`{colors.charcoal}`) for list items.
- **Body** (`{colors.body}`) for paragraphs, labels and the footer. The most
  used text colour after ink.
- **Mute** (`{colors.mute}`) for captions, placeholders and terminal comments.
- **On dark** and **On dark mute** for text inside the dark surface.

### Status: the traffic lights

The system has no error, success or warning palette. Vortex needs three
states on the wall, so it borrows the macOS terminal traffic lights and uses
them only as 8px dots (`{component.status-dot}`):

| Dot | Colour | Means |
| --- | --- | --- |
| `.dot.ok` | `{colors.terminal-green}` | submitted, line up, test passed |
| `.dot.warn` | `{colors.terminal-yellow}` | refused, escalated, unverified |
| `.dot.bad` | `{colors.terminal-red}` | failed, error, line down |
| `.dot.live` | `{colors.ink}`, pulsing | a call in progress |
| `.dot.off` | `{colors.hairline-strong}` | idle, skipped |

The dot carries the colour. The label next to it stays ink or body grey. Do
not colour text, borders or backgrounds by status.

### Focus

`{colors.focus-ring}` is the translucent blue browser focus ring. It is the
only blue in the system and it appears only on keyboard focus.

## Typography

- **Display**: SF Pro Rounded at weights 500 and 600, for `display-xl`,
  `display-lg` and `heading-lg`. The CSS stack is `"SF Pro Rounded",
  ui-rounded, "Nunito", system-ui`. Nunito loads from Google Fonts as the
  substitute on Windows and Linux.
- **Body**: `ui-sans-serif` then `system-ui`. Every role from 12px to 20px.
- **Code**: `ui-monospace` then SFMono, Menlo, Consolas.

| Token | Size | Weight | Line height | Use |
| --- | --- | --- | --- | --- |
| `{typography.display-xl}` | 36px | 500 | 1.11 | page headline, once per page |
| `{typography.display-lg}` | 30px | 500 | 1.2 | section headline, big numbers |
| `{typography.heading-lg}` | 24px | 600 | 1.33 | subsection, dark strip text |
| `{typography.heading-md}` | 20px | 500 | 1.4 | card title, patient name |
| `{typography.heading-sm}` | 18px | 500 | 1.56 | brand in the nav, FAQ question |
| `{typography.body-md}` | 16px | 400 | 1.5 | default prose, transcript |
| `{typography.body-strong}` | 16px | 500 | 1.5 | inline emphasis |
| `{typography.body-sm}` | 14px | 400 | 1.43 | list rows, key/value rows |
| `{typography.body-sm-strong}` | 14px | 500 | 1.43 | pill text, kicker, nav link |
| `{typography.caption-sm}` | 12px | 400 | 1.33 | footer, timestamps, who spoke |
| `{typography.code-md}` | 16px | 400 | 1.5 | install pill |
| `{typography.code-sm}` | 14px | 400 | 1.43 | terminal card, tool names, ids |
| `{typography.button-md}` | 14px | 500 | 1 | every button |

No letter-spacing. No uppercase labels. No italic. The heading scale is
tight (36 → 30 → 24 → 20 → 16) so the page reads as one column.

## Layout

- Base unit 8px. Tokens `{spacing.xxs}` to `{spacing.xxl}` for inline gaps,
  `{spacing.section}` (88px) between major blocks. Tablet 64px, mobile 48px.
- Reading column 720px (`.container`). Wide grids 960px (`.container-wide`).
  The wall uses the full viewport (`.container-full`) because it is a
  projector, not a document.
- Cards pad `{spacing.xxl}`. Compact cards pad `{spacing.lg}`.
- Grids of tiles use a 1px `{colors.hairline}` gap on a hairline background
  (`.stat-grid`). No inner borders, no shadows.

## Elevation and depth

| Level | Treatment | Use |
| --- | --- | --- |
| 0 | nothing | headline, prose, footer |
| 1 | 1px `{colors.hairline}` border | cards, terminal card, dividers |
| 2 | `{colors.surface-dark}` fill | the one "look here" per page |

There is no shadow anywhere. Depth is a border or an inversion, never a lift.

## Shapes

| Token | Value | Use |
| --- | --- | --- |
| `{rounded.none}` | 0 | nav, footer, dividers |
| `{rounded.sm}` | 6px | inline `<code>` |
| `{rounded.md}` | 8px | dropdown panels, rare |
| `{rounded.lg}` | 12px | cards, terminal card, speech bubbles |
| `{rounded.full}` | 9999px | buttons, pills, inputs, dots |

Two shapes carry the system: pills for anything interactive, 12px for cards.
Do not soften pills to 8px. Do not round cards to 9999px.

## Components

Class names in `design.css` match the YAML keys. Use them as they are.

### Buttons

- `.button-primary`: black pill, white text, 36px tall. The one CTA.
- `.button-secondary`: white pill, ink text, `{colors.hairline-strong}` border.
- `.button-pill-on-dark`: white pill inside a dark surface.
- `.button-disabled`: soft grey pill, mute text.

In NiceGUI: `ui.button("Play").classes("button-primary")` with
`.props("unelevated no-caps")`. `board.css` strips the Quasar defaults.

### Inputs

- `.search-pill`: soft grey pill, 36px. Flips to white on focus.
- `.text-input`: white pill with a hairline, 40px. Ink border on focus.

### Code

- `.install-snippet`: the signature pill for one command.
- `.command-tag`: a small inline chip for a tool name or a route.
- `.terminal-card` with `.terminal-traffic-lights`: a transcript, a log, a
  tool trace. Comments go in `.comment` (`{colors.mute}`).

### Cards

- `.card`: hairline, `{rounded.lg}`, 32px padding. `.card-compact` pads 16px.
- `.card-dark`: the inverted card. One per page.
- `.cta-strip-dark`: a dark band with `{typography.heading-lg}` text.
- `.stat-grid` and `.stat`: number tiles in a hairline grid.
- `.kv`: a key on the left in body grey, a value on the right in ink.
- `.faq-row`: question in `heading-sm`, answer in body grey, hairline below.
- `.feature-bullet`: a check mark and `body-sm` charcoal text.

### Pills and dots

- `.pill`: a neutral tag. `.pill.soft` for a grey fill, `.pill.dark` for the
  inverted tag, `.pill.mute` for grey text.
- `.dot` with `.ok`, `.warn`, `.bad`, `.live`, `.off`. See the status table.
- `.chip` and `.chip[aria-pressed="true"]`: filter chips. Pressed is black.

### Navigation and footer

- `.primary-nav`: 56px, canvas background, hairline below. Brand at the left
  as the mark plus "Vortex" in `heading-sm`. Links in `body-sm-strong`.
- `.footer-section`: hairline above, `caption-sm` links, centred.

### Transcript

- `.turn.user` and `.turn.assistant` with `.who` and `.bubble`. The agent's
  bubble is soft grey. The patient's bubble is white with a hairline.

## The wall, specifically

The jury reads the wall from three metres away for ten seconds. Three columns:
the transcript, the tool trace inside a terminal card, and the record with the
verdict. The verdict is the page's one dark surface. Nothing else competes.

- The headline is the clinic name in `display-lg`. The call id sits in a
  `.pill.mute.mono` at the right.
- "En llamada" is a `.pill.dark` with a `.dot.live`. Any other state is a
  `.pill` with the matching dot.
- Tool steps are rows in a terminal card: dot, name in `code-sm`, the
  duration in `caption-sm` body grey at the right.

## Do

- Treat the page as a document. One column, air between sections.
- Use `.button-primary` for every primary action. Never a coloured button.
- Default to `{rounded.full}` for interactive elements, `{rounded.lg}` for cards.
- Put commands, ids, tool names and routes in `code-sm` or a `.command-tag`.
- Use one `{colors.surface-dark}` surface per page. Pick the thing the reader
  must see and invert that.
- Load `design.css` first and keep page CSS short.

## Don't

- No gradients, no shadows, no background images.
- No brand colour, no lane colour, no chart palette. Status dots only.
- No uppercase labels with letter-spacing. Use `body-sm-strong` in body grey.
- No branded body font. `system-ui` is the point.
- No dark mode. The canvas is white in every room.
- No page-local `:root` tokens. If a value is missing, add it to the system.

## Responsive behaviour

| Name | Width | Changes |
| --- | --- | --- |
| desktop | 1024px+ | 720px column, three-column wall, 3-up grids |
| tablet | 850px | `{spacing.section}` 64px, grids 2-up, wall columns stack |
| narrow | 768px | grids 1-up, nav wraps |
| mobile | 640px | `display-xl` drops to 28px, `{spacing.section}` 48px |

Touch targets: buttons and pills 36px, inputs 40px, footer rows 32px.

## Lint

`npx @google/design.md lint DESIGN.md` reports broken references, contrast
and orphaned tokens. Run it after you edit the front matter.

## Known gaps

- Hover states are not documented, by policy. Pressed states are.
- The board still runs on NiceGUI (Quasar). `board.css` overrides Quasar's
  buttons, inputs and notifications to match. New Quasar widgets need a
  matching override before they ship.
- Dark mode does not exist. A projector in a dark room still gets white.
