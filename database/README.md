# database/

An auxiliary, refreshable cache of clinic availability — not wired into anything
yet. Every tool in `vortex/` still calls the clinic API directly, unchanged.

- `scripts/refresh_slots.py` — run it to (re)build `processed/`:

  ```bash
  uv run python database/scripts/refresh_slots.py
  ```

- `processed/` — generated output (gitignored, not committed):
  - `slots_by_specialty.json` — `{specialty_id: [slot, ...]}`, slots sorted by start
    time, plus `blocked_by_specialty` (see caveat below).
  - `provider_specialty.json` — `{provider_id: specialty_id}`, the static catalogue fact.

Why keyed by specialty and not by provider or appointment type: every provider
belongs to exactly one specialty, so "by provider" is a strict subset of "by
specialty" — filtering an already-small, already-sorted specialty bucket by
`provider_id` is cheap, with no need for a second parallel index.
`appointment_type` is never something a caller asks for directly (it follows the
patient's record, per the clinic docs), so it stays a plain field on each row
rather than its own index.

## `blocked_by_specialty` — what it does and doesn't cover

Fetched day by day, deliberately: confirmed against the live API that `blocked`
only lists a provider when they're blocked for the **entire** requested window,
not a partial overlap. A `<=14`-day chunk missed Dr. Requena's real 14–30 Sept
leave outright (no chunk boundary happened to land exactly on his leave dates) —
only day-by-day gets this right, at the cost of a few hundred calls instead of ~18
(confirmed live: 762 slot rows either way, 17 correct `provider_on_leave` entries
for Sept 14–30 day-by-day vs. 0 with 14-day chunks).

This is fetched with **no `patient_id` and no `insurer`** (it's one specialty-wide
structure, not one per patient), so it only ever captures `provider_on_leave`,
`location_hours` and `type_not_offered` — schedule/catalog facts true regardless
of who's asking. The other 8 `DeclineReason`s that `check_eligibility` cares about
(`specialty_not_covered`, `referral_required`, `insurer_referral_required`,
`allowance_exhausted`, `provider_not_in_network`, `not_eligible_age`,
`patient_history`, insurer-scoped `location_not_covered`) only appear once the API
knows which patient/insurer is asking — fundamentally per-call state this cache
cannot precompute. **`check_eligibility` still needs a live, patient-and-insurer
-scoped call regardless of anything in this folder.**
