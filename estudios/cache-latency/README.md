# Cache vs. no-cache: latency study of the tool layer

Date: 2026-09-19. Scope: every tool in `vortex/tools.py`, measured across the
current client, a fresh client, and an in-memory snapshot. The live runs use the
real production API; the API key is supplied only through the environment and
is never written to the repository.

```bash
uv run python estudios/cache-latency/bench.py
PLATFORM_API_KEY=... uv run python estudios/cache-latency/bench.py --live
```

The committed `results.json` is the output of the second command with the
script default of **25 timed repetitions per tool per scenario**.

## Caching strategies

- **live_no_cache** - real production API, fresh `ClinicClient` for each call.
  It pays connection setup and fetches the catalogue again when needed.
- **live_current** - real production API with today's shared `ClinicClient`.
  The catalogue is cached; directory, availability, and appointments stay live.
- **full_memory** - the lower bound with clinic data already local.

The benchmark is read-only against production. Submit routes are never called.

## Headline numbers

Real HTTPS floor to the production host:

| request | p50 | p95 |
|---|---:|---:|
| `/api/v1/health`, warm keep-alive | 145.8 ms | 249.2 ms |
| `/api/v1/health`, fresh connection | 436.8 ms | 459.1 ms |
| unauthenticated `/api/v1/clinic` (403 floor) | 146.4 ms | 436.2 ms |

Measured p50 latency, 25 runs per tool:

| tool | live no-cache | live current | warm in-memory |
|---|---:|---:|---:|
| find_patient | 458.2 ms | 167.2 ms | 0.038 ms |
| validate_national_id | 0.169 ms | 0.005 ms | 0.005 ms |
| build_registration | 618.9 ms | 0.229 ms | 0.204 ms |
| resolve_date | 657.0 ms | 0.034 ms | 0.033 ms |
| find_slots | 835.0 ms | 217.3 ms | 0.859 ms |
| list_appointments | 507.9 ms | 211.3 ms | 0.021 ms |
| prepare_booking | 823.2 ms | 212.7 ms | 0.112 ms |
| prepare_reschedule | 673.4 ms | 375.0 ms | 0.063 ms |
| prepare_cancel | 881.1 ms | 603.0 ms | 0.046 ms |
| check_eligibility | 1152.1 ms | 391.6 ms | 1.787 ms |
| triage | 0.472 ms | 0.089 ms | 0.087 ms |
| nearest_location | 608.1 ms | 0.206 ms | 0.177 ms |
| find_provider | 607.7 ms | 0.038 ms | 0.021 ms |
| clinic_facts | 609.2 ms | 0.045 ms | 0.018 ms |

The catalogue cache is already effective: catalogue-only tools drop from about
609 ms with a fresh client to below 0.25 ms with the shared client. The largest
remaining costs are the routes that still query patients, availability, or
appointments.

A normal booking chain (`find_patient` + `check_eligibility` + `find_slots` +
`prepare_booking`) is **988.7 ms p50** against the real API today versus **2.8
ms** with a warm snapshot. That is a measured saving of **985.9 ms** per chain.

## Cache build cost

The real live snapshot pass took **8.713 s** and pulled **762 slots**, **4
matched patients**, and **10 appointments** over the production calendar
2026-09-07 to 2026-10-16. The production API does not expose response byte or
request counters to the client, so those fields remain `null` in
`cache_build_live`.

For a controlled count of the algorithm itself, the equivalent fixture run is
**48 requests**, **712,736 response bytes**, and **0.156 s**, yielding 2,775
fixture slots. This makes clear what is network/server time versus local work.

Directory and appointments cannot be globally prefetched: directory requires a
search key and appointments require a patient ID. Those caches must fill as
patients are seen, with write-through updates after registrations and bookings.

## Storage bake-off

At the documented scale of about 3,000 patients (synthetic rows with the real
schema, plus 6,000 appointments and 2,775 fixture slots):

| backend | build/load | size | hot query |
|---|---|---:|---:|
| in-memory indexes | 1.9 ms build | ~3.06 MB serialized floor | 0.19 µs by phone |
| JSON snapshot | 19.9 ms build / 24.8 ms load | 3.06 MB | 0.241 ms full scan |
| SQLite | 81.2 ms build | 3.88 MB | 10.1 µs by phone; 61.6 µs slots/day |
| Redis | external service + network hop | - | cannot beat the local lookup enough to justify itself |

## Gains, losses, and safety

1. **Availability freshness.** Snapshot availability at startup and invalidate
   slots on the process's own book/cancel/reschedule writes. Keep
   `prepare_booking`'s live availability re-check as the correctness gate.
2. **Directory and appointments.** Cache patients as they are seen and update on
   registration. Keep appointments live or use a short TTL because they change
   often and cannot be bulk-listed.
3. **Concurrent calls.** Two calls may see the same cached slot. The live
   `prepare_booking` re-check remains the guard against double-booking.
4. **Storage.** The dataset is only a few MB. One JSON snapshot is enough for
   persistence; SQLite becomes useful only for multi-process sharing or richer
   queries. Redis is unnecessary at this scale.

## Recommendation

Keep the working catalogue cache. Add a startup availability snapshot with
write-through invalidation, extend the patient stash to process lifetime, keep
appointments live or at TTL <= 30 seconds, and preserve the live
`prepare_booking` re-check. Persist the snapshot as JSON; move to SQLite only
if the service becomes multi-process.

## Method and limits

`bench.py` runs every registered tool through its production code path. Local
scenarios use an HTTP server backed by the repository fixtures, which isolates
HTTP/serialization and produces deterministic request and byte counts. Live
scenarios call the production API with the supplied key and report real
end-to-end timings. The storage study uses 3,000 synthetic patients in the real
payload shape. Exact WAN and server timings naturally vary by run and host.

Every clinic-side identifier a recipe needs (slot, `patient_id`,
`appointment_id`, specialty, location, provider, insurance plan) is resolved
against the client the scenario runs against, so a live run times production
ids. `/directory` only answers an exact field, so a live run can only reuse a
fixture patient production also knows: when it knows none, the recipes that
need a patient or an appointment are reported as `SKIPPED` rather than timed on
an id the platform would reject. The patient and the appointment are resolved
first, then the booking and the reschedule recipes each get their own slot,
warmed under the patient and plan that operation carries — availability answers
differently per patient, so a slot warmed without one is rejected by
`prepare_booking`'s re-check instead of timing a booking.
