# Control center — product plan

Date: 2026-09-19. Branch base: `origin/main` @ 6641828.
Status: spec for five parallel worktrees, each ending in a PR.

## Vision

The product gains a control center inside the React wall app (`vortex/wall`,
served at `/wall`, `/clinic` shell). Three sections in the `/clinic` nav:

1. **Live** — `/clinic/live-calls`. Every inbound call as a card/dot on a live
   scatter. Each call drifts toward its outcome corner (`book`, `reschedule`,
   `escalate`, `no-action`) as `call.intent` and tool events arrive. Caller
   identity resolves to a name when `find_patient` returns. A waveform strip
   animates by phase (`derive.js` phases: connecting / listening / thinking /
   working / speaking / ended). Simulated, not real audio.
2. **Calls** — `/clinic/calls`. A calls table in the Retell/Hamming pattern:
   a new row animates in when a call connects, shows `en curso` with a live
   wave while active, and swaps to an audio player plus a download button when
   the recording lands.
3. **Analytics** — `/clinic/insights` extended. Hamming-style call analytics:
   call status distribution, call duration histogram, talk ratio per call,
   words per turn per speaker, TTFB and tool-latency p50/p95, outcome funnel,
   cost per call. Reads SQLite, not the JSONL.

## Decisions taken

- Control center lives in the **React wall** (`/clinic`), not the NiceGUI
  console. The console keeps its pages unchanged.
- **Tailwind + shadcn** enter `vortex/wall` to adopt ElevenLabs UI
  selectively. Copied sources get re-skinned to `design.css` /
  `theme/tokens.css` tokens. No new brand colour, ever.
- The live wave is **simulated by phase**. No audio leaves the server while a
  call runs.
- Recordings **are** persisted: µ-law → WAV per call, so the Calls table can
  play and download finished calls.

## Data layer spec

All new surface is additive. No contract signature changes.

### New/changed events in `public.call_events`

| kind | fields | emitted by |
| --- | --- | --- |
| `call.intent` | `intent` in `book, register, reschedule, cancel, no-action, escalate` | conversation lane, when the caller's goal is classified or re-classified. Spec already at `wall_timeline.py:97`. |
| `turn.metrics` | `speaker`, `started_ts`, `ended_ts`, `words`, `ttfb_ms` (agent only) | line pipeline, one per `turn.user` / `turn.assistant`. Enables talk ratio, words/turn, TTFB percentiles. |
| `call.recording` | `path`, `format`, `duration_ms`, `bytes` | line, on `call.ended`, when a WAV was written. |

### New endpoints

| route | server | returns |
| --- | --- | --- |
| `GET /api/wall/calls/active` | board (`live.py`) | `[{call_id, from_masked, started_ts, stage, intent, phase, tools_run}]` — calls without `call.ended`. |
| `GET /recordings/{call_id}` | line (`server.py`) | the WAV file, `audio/wav`, `Content-Disposition` for download. |
| `GET /api/wall/analytics?days=N` | board | aggregates read from Supabase: status mix, duration buckets, talk ratio, words/turn, TTFB p50/p95, outcome funnel, cost. |

### Persistence

- Recordings: `recordings/{call_id}.wav`, written by the line at `call.ended`.
  Git-ignored. `VORTEX_RECORDINGS_DIR` overrides the path.
- Everything else: Supabase/Postgres, the one persistent store. The line writes
  `public.call_events` as the call happens; the aggregate tables (`calls`,
  `turns`, `tool_calls`, `submissions`, `usage`) are derived from it in the same
  database, so there is nothing to ingest and nothing to rebuild. Schema lives
  only in `database/supabase/migrations/NNNN_*.sql`, applied with
  `make supabase-migrate`. There is no SQLite file and no JSONL log.

## Workstreams — one worktree, one PR each

| worktree | branch | owns | must not touch |
| --- | --- | --- | --- |
| `wt-cc-plan` | `docs/control-center-plan` | this doc, `docs/tasks.json` | code |
| `wt-cc-data` | `feat/cc-data-layer` | `vortex/line/` (recording, `turn.metrics`, `call.intent` hook), `vortex/observability/` (`/api/wall/calls/active`), tests | `vortex/wall/` |
| `wt-cc-design` | `feat/wall-shadcn-ui` | `vortex/wall` toolchain: Tailwind, `components.json`, `src/components/elevenlabs/`, `package.json`, token mapping | pages, routes |
| `wt-cc-live` | `feat/clinic-live-calls` | `src/pages/clinic/LiveCalls*`, `src/lib/` additions, router entry | `package.json`, `vortex/` python |
| `wt-cc-calls` | `feat/clinic-calls-table` | `src/pages/clinic/Calls*`, `src/lib/` additions, router entry | `package.json` (adds deps only if unavoidable — prefer the design worktree's components), `vortex/` python |
| `wt-cc-analytics` | `feat/clinic-analytics` | `vortex/observability/store.py` + `/api/wall/analytics`, `src/pages/clinic/Insights*` extension, router entry | `vortex/line/`, other pages |

Coordination rules for the parallel PRs:

- Fronts build against the **documented** endpoints above and keep the
  existing mock fallbacks (`lib/mockTimeline.js` pattern) so pages render
  before the data PR merges.
- Only `wt-cc-design` edits `package.json`, Tailwind config and
  `components.json`. Other fronts assume `bar-visualizer`, `live-waveform`,
  `audio-player`, `transcript-viewer` will exist under
  `src/components/elevenlabs/` after merge; until then they use
  `design.css`/tokens primitives and leave a single seam (`components/`
  wrapper) to swap.
- Every PR: `make test`, `make lint`, `npm run build` where applicable.
  New copy strings in `explain.py` style — plain words, no jargon.
- No shared state between calls (hard rule 3). The line only ever appends its
  own events; it never reads another call's rows back.

## Reference products (why each choice)

- **Retell** — live call list with ticking durations, silent listen-in,
  column-rich history, chart-builder analytics. The Calls + Live pattern.
- **Hamming** — call status, call duration, talk ratio, live analytics, alert
  thresholds. The Analytics pattern.
- **LiveKit Cloud Observability** — synced audio + turn-by-turn span timeline.
  The per-call zoom already does this; keep it.
- **Hyro Care Intelligence** — clinical command-center KPIs. Jury-facing
  framing for Insights.
- **ElevenLabs UI** (MIT, shadcn registry `ui.elevenlabs.io`) —
  `bar-visualizer`, `live-waveform`, `audio-player`, `transcript-viewer`,
  `message`/`conversation`. Skip `orb` (needs R3F 8 on React 18).
- **wavesurfer.js** (BSD-3) — recording playback fallback; also usable inside
  NiceGUI via vanilla JS if needed later.

## Pitch framing

The multi-provider evals platform stays a *feature*, not the company: "the
evals harness accepts any agent that speaks Twilio Media Streams." The wedge
is the clinic agent with evals as proof (audit trail, scored runs). Coval,
Hamming, Cekura and Roark already own "vendor-neutral voice evals" as a pitch;
the jury story sells the agent plus the evidence it works.
