---
name: design-system
description: How every Vortex screen looks. Read before you change HTML, CSS, a NiceGUI page, the mic page or the evals report.
---

# Design system

The source of truth is `DESIGN.md` at the repo root. Read it first. This skill
tells you where the pieces are and what to do, not what the system is.

## Files

| File | Role |
| --- | --- |
| `DESIGN.md` | tokens (YAML front matter) and the rules |
| `vortex/observability/design.css` | the tokens as CSS plus the components; every front end loads it first |
| `vortex/observability/board.css` | Quasar overrides and the wall/ops layouts, nothing else |
| `docs/design.css` | a copy for GitHub Pages; `make design-sync` refreshes it |
| `tests/test_design.py` | fails when the copy is stale or a token is missing |

## Procedure: change a screen

1. Read `DESIGN.md`, sections Components and Do/Don't.
2. Find a class in `design.css` that already does the job. Use it.
3. If no class fits, add a component to `DESIGN.md` first, then to `design.css`.
4. Never add a colour. Status uses `.dot.ok`, `.dot.warn`, `.dot.bad`, `.dot.live`, `.dot.off`.
5. Keep one `surface-dark` element per page. If you add a second, remove the first.
6. Run `make design-sync`, `make fmt`, `make test`.
7. Look at the result. Headless Chrome works without a session:
   `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --screenshot=out.png --window-size=1440,900 <url>`

## NiceGUI specifics

- `_apply_chrome()` in `live.py` sets `ui.dark_mode(False)`, `ui.colors(primary="#000000", ...)` and loads both stylesheets. Call it at the top of every page.
- Quasar paints its palette with `!important` inside a cascade layer. A plain CSS override of `background` on a `.q-btn` loses. Make the palette black with `ui.colors` and shape the rest in `board.css`.
- Buttons: `.props("unelevated no-caps").classes("button-primary")` for the CTA, `.props("outline no-caps").classes("button-secondary")` for the rest, `.props("flat no-caps").classes("button-quiet")` for the quiet one.
- Inputs: `.props("dense outlined")`. `board.css` turns them into pills.
- Labels are `<div>`s. Give them a text role class: `heading-lg`, `body-sm`, `kicker`, `caption-sm`.

## Static and generated pages

- `docs/*.html`: `<link rel="stylesheet" href="design.css">` before the page `<style>`. Page CSS only lays out; tokens come from the link.
- `vortex/line/mic.html`: same, via `<link href="/design.css">`. `server.py` serves the file.
- `evals/common/report.py`: inlines `design.css` at render time. Keep `_CSS` to layout.
