# Cache vs. no-cache: latency study of the tool layer

Date: 2026-09-19. Scope: every tool in `vortex/tools.py`, measured three ways,
plus the cost of building a full local snapshot and a bake-off of where that
snapshot can live. Reproduce everything here with:

```bash
uv run python estudios/cache-latency/bench.py                 # offline study (this file's numbers)
PLATFORM_API_KEY=... uv run python estudios/cache-latency/bench.py --live   # swap in live API numbers
```

All numbers below come from `results.json` (60 timed repetitions per tool per
scenario, this machine, 2026-09-19). `bench.py` regenerates both files.

## The three caching strategies compared

- **no_cache** - a fresh HTTP client per call: every call pays TCP+TLS, HTTP
  and JSON parse, and even the catalogue is re-fetched. The worst case.
- **current** - what production does today: one shared `ClinicClient`, the
  catalogue cached in-process, every directory/availability/appointments
  query still goes out over HTTP.
- **full_memory** - everything already local (`FakeClinicClient`): the lower
  bound a warm snapshot cache buys.

The API side is a local server that speaks the platform's routes and serves the
repo's own raw fixtures, so HTTP, serialization and adaptation costs are real;
what it cannot include is the wide-area network and the organisers' server-side
work. The WAN part is measured separately (network floor, below) and the sum
`full_memory + requests x floor` is the honest estimate for production.

## Headline numbers

Network floor to the production host (measured, real HTTPS):

| path | p50 | p95 |
|---|---|---|
| `GET /api/v1/health`, warm keep-alive connection | 145 ms | 355 ms |
| same, fresh connection (TCP+TLS each time) | 435 ms | 461 ms |
| `GET /api/v1/clinic` unauthenticated (403 - lower bound for an authed call) | 145 ms | 174 ms |

Tool latency, p50 ms (p95 in brackets), 60 runs each:

| tool | API requests per call (current) | no_cache | current | full_memory | estimated live today* |
|---|---|---|---|---|---|
| find_patient | 1.98 (directory + appointments prefetch) | 3.5 (11.8) | 5.1 (6.3) | 0.04 | ~290 ms |
| validate_national_id | 0 | 0.19 | 0.005 | 0.005 | ~0 ms |
| build_registration | ~0 | 3.4 (17.4) | 0.21 | 0.20 | ~0 ms |
| resolve_date | 0 | 3.0 (15.6) | 0.03 | 0.03 | ~0 ms |
| find_slots | 1 (availability) | 7.8 (10.9) | 4.0 (5.6) | 0.86 | ~146 ms |
| list_appointments | 1 (appointments) | 3.2 (5.9) | 2.6 (3.2) | 0.02 | ~145 ms |
| prepare_booking | 1 (availability re-check) | 5.8 (14.7) | 2.5 (3.1) | 0.11 | ~145 ms |
| prepare_reschedule | 2 (directory + appointments) | 4.7 (18.9) | 5.5 (6.2) | 0.06 | ~290 ms |
| prepare_cancel | 2 (directory + appointments) | 4.8 (21.3) | 5.3 (6.2) | 0.05 | ~290 ms |
| check_eligibility | 2 (directory + availability) | 10.5 (15.9) | 8.1 (10.0) | 1.77 | ~292 ms |
| triage | 0 | 0.33 | 0.09 | 0.09 | ~0 ms |
| nearest_location | 0 (catalogue) | 3.4 (15.1) | 0.17 | 0.17 | ~0 ms |
| find_provider | 0 (catalogue) | 3.2 (13.3) | 0.02 | 0.02 | ~0 ms |
| clinic_facts | 0 (catalogue) | 3.3 (16.4) | 0.02 | 0.02 | ~0 ms |

\* `full_memory p50 + requests x 145 ms keep-alive floor`. Rerun with `--live`
to replace these estimates with measured live numbers.

Read: the catalogue cache already works - catalogue-only tools are free after
warm-up. Everything that touches a *patient* still pays 1-2 WAN round trips per
tool call. A normal booking call chains find_patient + check_eligibility +
find_slots + prepare_booking: about **0.9 s of dead air** today that a snapshot
cache turns into ~3 ms. reschedule/cancel paths pay ~290 ms per tool on top.

## What it costs to cache everything (build time)

Full local pull of the fixture clinic: **48 requests, 713 KB, 0.23 s** wall
(1 catalogue + 6 specialties x 3 fourteen-day spans of availability + 15
directory lookups + their appointments; 2,775 slots). The platform calendar is
fixed for the event (2026-09-07 to 2026-10-16) and the docs say to cache the
catalogue freely, so at production scale this stays a one-off cost of a few
seconds at process start. The directory and per-patient appointments **cannot
be prefetched by design**: `/directory` rejects parameter-less queries (422)
and appointments are per-patient only. Those two caches can only be
populated as calls see patients (write-through when we register someone).

## Where the snapshot can live (storage bake-off)

At the documented scale (~3,000 patients; synthetic rows, real bytes and
queries; plus the real 2,775-slot pull):

| backend | build | size | hot query | notes |
|---|---|---|---|---|
| in-memory dicts | 2 ms | ~3 MB JSON floor (2-4x as live objects) | 0.1 µs by phone | fastest; dies with the process; one process = all sockets share it |
| single JSON snapshot | 27 ms | 3.1 MB | 0.18 ms full scan | survives restarts, trivially inspectable; scan is already fast enough at 3k patients |
| SQLite | 115 ms | 3.9 MB | 8 µs by phone, 58 µs slots-by-day | survives restarts, multi-process safe; overkill at this size |
| Redis / external | - | - | - | adds infra and a network hop to beat 0.1 µs - rejected outright |

## What we gain, what we lose

Gain: ~0.9 s less dead air per booking call, ~290 ms less on
reschedule/cancel/eligibility; near-zero marginal cost per call after a
sub-second startup pull; evals and tests are untouched (they already run on
the fake client).

Lose / risks, with the mitigation this study supports:

1. **Availability goes stale on our own writes.** The platform stops offering
   a slot the moment we book it; a snapshot would keep offering it. Mitigate:
   write-through invalidation on book/cancel/reschedule, and keep
   `prepare_booking`'s existing live availability re-check as the safety gate
   (it is 1 request, ~145 ms, exactly where correctness matters).
2. **Directory/appointments change when we register or book.** Cache-as-seen
   with write-through on `submit/register`; keep `list_appointments` live or
   on a short TTL - it is the most volatile route.
3. **Concurrent calls.** Two sockets can see the same cached free slot. The
   live re-check in `prepare_booking` is the guard; the snapshot only narrows
   the search.
4. **Memory.** A few MB per process. Not a constraint.

## Recommendation

1. Keep the catalogue cache (done).
2. Build an availability snapshot at process start (48 requests, sub-second)
   with write-through invalidation on our own bookings; keep the live
   re-check inside `prepare_booking`.
3. Extend the per-call patient record stash to process lifetime,
   write-through on register.
4. Keep appointments live (or TTL <= 30 s).
5. Persist the snapshot as one JSON file; move to SQLite only if the line
   ever runs multi-process.

## How this was produced / limitations

- Script: `bench.py` (this folder). Local platform server serves the repo's
  raw fixtures over HTTP; tools run through their real production code paths;
  WAN floor measured against the production host (200 on `/health`, 403 floor
  on data routes, no key needed for either).
- Not measured without a team API key: the organisers' server-side time per
  route and real production payload sizes. `PLATFORM_API_KEY=... --live`
  fills both in; every `estimated live today` cell above is the place those
  numbers land.
- Fixture scale is 15 patients; the 3,000-patient storage numbers use
  synthetic rows of the real shape and are labeled synthetic in
  `results.json`.
