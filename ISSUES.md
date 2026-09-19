# Issues

Local stand-in for GitHub issues — `gh` isn't installed/authenticated in this
environment, so these are tracked here until someone can file them for real
(`gh issue create --title "..." --body-file ...` from this file's entries).

---

## Migrate Pathways builder + patterns data (JSON seeds) to the real database

Everything below is currently a flat-JSON stand-in, per an earlier decision to
prototype in JSON before a real backend/DB exists:

- `vortex/wall/src/data/pathways.json` (formerly `workflows.json`) — the seed
  pathways (nodes, shape, when rules, descriptions).
- `vortex/wall/src/data/shapeTypes.json` — the calls/messages/visits catalog
  (type, subfamily, emoji, defaultWhen).
- `vortex/wall/src/data/patterns.json` (formerly `basicWorkflows.json`) —
  proposed "pattern" definitions (patient-history sequence matching →
  suggested action on a call). This is a design proposal, not implemented
  against real data anywhere yet. 4 of its 6 patterns are buildable today from
  `GET /patients/{id}/appointments` (visits) and `GET /submissions` filtered
  by `patient_id` (book/reschedule/cancel outcomes); 2 of them
  (`no-availability-unrecovered`, `repeat-callers-unresolved`) need a future
  patient-indexed call log that doesn't exist yet (`no_action`/`escalate`
  submissions carry no `patient_id` today).
- `vortex/wall/src/data/patientTimelines.json` — mock per-patient
  call/message/visit history used by the new Patient Timeline view.
- localStorage key `vortex.pathways.v1` (see `STORAGE_KEY` /
  `loadStoredState` / `handleSave` in `Pathways.jsx`) — manual "Save"
  persistence in the browser, including a `migratePathways`/
  `migrateCallShape()` pass that upgrades old-shape call nodes on load.

**TODO once the actual database is configured:**
- Design a proper schema for pathways/nodes, the shape-types catalog, and
  the pattern definitions + their match results.
- Replace the JSON imports with real fetch calls to backend endpoints.
- Replace the manual localStorage save/load with real API persistence
  (keeping the same manual "Save" UX if desired).
- Carry over the existing migration logic (or an equivalent) so any pathway
  someone already saved locally isn't lost/broken by the schema change.
- Build the patient-indexed call log that pattern rules 5-6 need (today calls
  only exist as unindexed per-call JSONL eval logs and as `no_action`/
  `escalate` submissions with no `patient_id`).

---

## Accepting a call suggestion must actually schedule an outgoing call

In the Patient Timeline view, accepting (✓) a pattern-matched suggestion
currently only marks it accepted in the UI — it doesn't do anything real.

**TODO:** once there's a real backend, accepting a suggestion should actually
schedule/trigger an outgoing call to the patient (i.e. hand off to whatever
the platform uses to place outbound calls), not just flip a UI state.

---

## Rejecting a suggestion must record the rejection in the real database

In the Patient Timeline view, rejecting (✕) a pattern-matched suggestion
removes it immediately and remembers it so that same pattern never resurfaces
for that patient — but today that memory is only a localStorage stand-in
(`vortex.rejectedSuggestions.v1`, see `loadRejectedMap`/`saveRejectedMap` in
`PatientTimeline.jsx`), keyed by `patient_id` → list of rejected pattern ids.

**TODO:** once there's a real backend/database, persist the rejection there
instead (patient_id + pattern id + timestamp), and have the match-finding
step (`findMatchingPattern`) exclude already-rejected patterns server-side
rather than filtering them out client-side after the fact.
