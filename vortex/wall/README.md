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
- `src/designs/design11/` is the Live Call detail view actually in use
  (embedded by `LiveCallDetail.jsx`). `src/designs/` also holds ten other,
  untouched historical concepts — don't "clean those up"; they're kept for
  reference. Swapping which one the app embeds is one import.
