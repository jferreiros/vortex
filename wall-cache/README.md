# wall-cache/

Precomputed stats the Clinic View's Home page renders straight from disk,
instead of hitting the clinic API (or replaying `synthetic-data/`) on every
request. Built by `scripts/precompute_wall_cache.py`, which calls the same
`vortex.clinic.make_clinic_client()` every lane uses — live GETs against the
Prosper platform when `PLATFORM_API_KEY` is set, the offline fixtures
otherwise — and postprocesses the responses into the shape the wall wants.

Regenerate by hand:

```bash
uv run python scripts/precompute_wall_cache.py
```

It also runs once, automatically, every time `make board` starts (see
`vortex/observability/live.py`'s `main()`), so the file is never more than
one process lifetime stale. `vortex/observability/home_overview.py` reads it
directly; nothing here calls the clinic API at request time.

## Files (generated, gitignored — not committed)

- `occupancy.json` — the "Tasa de ocupación" widget's numbers:
  - `sites`, `specialties` — `{id, name}`, straight off the catalogue
    (`GET /clinic`), for the Home page's filter dropdowns.
  - `bookable_from` / `bookable_to` — the platform's own bookable calendar
    window; occupancy is only ever computed inside it.
  - `days[].cells[]` — one row per `(location_id, specialty_id)` that has any
    open capacity that day: `capacity_slots` (a provider's open minutes /
    15, zeroed on a leave day or a clinic closure day) and `busy_slots`
    (`capacity - free`, where `free` is what `GET /availability` actually
    still offers). The Home page's site/specialty filters just sum matching
    cells at read time — nothing here is pre-filtered.

## Why this exists as its own folder, not under `database/`

`database/processed/` is a sibling cache with a different job: a
day-by-day mirror of raw slots and `blocked` entries for tool-side reuse,
kept day-by-day specifically because `blocked` needs that precision (see
its own README). This folder holds the Home page's own postprocessed
aggregates (capacity vs. busy, already summed to what the UI draws), fetched
in <=14-day chunks since only slot *counts* matter here — chunking changes
nothing about the total, just the number of GETs.
