# vortex/wall — the React app

The SPA behind `/call/{call_id}/zoom`: Landing page, the per-call "zoom" view
(voice orb, live tool demo, extracted info), and the Clinic View (Home,
Settings, Insights, Live Calls). Not to be confused with `make board`'s own
`/wall` route — that's the NiceGUI jury projector page, served straight from
`vortex/observability/live.py`. This app is a separate stack living
alongside it: React 18 + Vite + `react-router-dom` (`HashRouter`, so the
whole SPA's routing lives after the `#` — see `AppRouter.jsx`) +
`@react-spring/web` for eased/discrete animations. No CSS framework: each
page's own stylesheet reads colour/type/spacing/radius/shadow/motion from
`src/theme/tokens.css`, never a hardcoded value (see that file's own
comment). No other runtime dependencies — check `package.json` before adding
one.

## Where the data comes from

`/api/wall/*` and nothing else. The handlers live in `vortex/api/` — one
module per topic (`timeline.py`, `live_calls.py`, `agenda.py`,
`analytics.py`, `settings.py`, `patient_timeline.py`, `voice.py`), each an
`APIRouter` mounted once under `/api/wall` by `vortex/api/wall.py`'s
`attach(app)`. Same origin as this app, so no CORS and no second process.
Behind them is Supabase/Postgres: there is no SQLite file, no
`logs/calls.jsonl`, and the SPA never talks to Supabase itself (the
service-role key is server-side only, and there is no Realtime subscription
here — the live pages use SSE off `/api/wall/*/stream`).

There are no mock fixtures left in `src/`. A page with nothing to show
renders its empty state and waits for the endpoint; it does not invent
numbers. The two documents the Pathways and Patterns editors edit live in
the `wall_documents` table and are seeded once by
`database/seed/wall_documents.sql`.

`src/data/` still holds `shapeTypes.json` and `patternShapes.json`. Those
are the editors' tray vocabulary — families, types, emoji, labels, gap
units — not clinic data, and nothing in the product writes them, so they
stay in the bundle.

## Local dev

```bash
npm install
npm run dev          # Vite, prints its own port (5173 if free)
```

Also run `make board` (repo root) alongside it — Vite's dev server proxies
`/api/wall/*` and the `/wall/*` avatar image routes to it on `:8080`. Without
it, the app still loads but the avatar images 404.

Open `http://localhost:<port>/wall-assets/#/` (the `/wall-assets/` base
comes from `vite.config.js`'s `base`, which must match the static mount
FastAPI serves the built app from in production — see `live.py`'s
`app.add_static_files("/wall-assets", ...)`).

## Gotcha: the dev proxy allowlist

`vite.config.js` proxies specific `/wall/*` paths to the backend by name,
not a wildcard:

```js
proxy: {
  "/api/wall": "http://127.0.0.1:8080",
  "/wall/avatar2d": "http://127.0.0.1:8080",
  "/wall/vorty-face": "http://127.0.0.1:8080",
},
```

In production FastAPI serves everything from one origin, so this only bites
in dev: if you add a new backend-served image/asset route (another
`@app.get("/wall/...")` in `live.py`) and reference it from an `<img src=...>`
or `fetch`, add it here too, or it silently 404s only when running `npm run
dev` locally — it'll work fine once deployed, which makes it easy to miss.
This is exactly the bug behind the missing Vorty avatar in the call
transcript (fixed 2026-09-19) — the `/wall/vorty-face` line was missing.

## Patterns worth reusing

- **`src/pages/landing/useCrossfadeScroll.js`** — an eased, JS-driven
  scroll-to that fades a full-viewport veil (colour = the destination
  section's background) in, scrolls underneath it, then fades it out.
  Use this instead of `scrollIntoView({behavior: "smooth"})` anywhere a
  section change should read as a deliberate transition rather than an
  instant jump — see `Landing.jsx` for the wiring (veil element + passing
  `scrollToId` down to the trigger).
- **`src/pages/landing/useHeroScroll.js`** vs. `Reveal.jsx`'s spring: read
  the comment in `useHeroScroll.js` for when to track scroll position
  directly (1:1, e.g. shrinking something as you scroll) vs. when to use a
  React Spring transition instead (a discrete on/off state, e.g. "has this
  scrolled into view").
- **`src/app/pageWipe.js` + `PageWipeOverlay.jsx`** — a full-screen wipe
  transition fired from anywhere (`triggerPageWipe(toPath)`) that covers the
  screen, swaps the route while covered, then reveals it. Mounted at the
  router root and ready to reuse; nothing wires it right now.
