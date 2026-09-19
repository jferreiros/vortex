# database/

The product's own database: two SQLite tables, `appointments` and `calls`,
answering "what did we book, and which call did it" — not a refactor of
`logs/calls.jsonl`, which stays exactly as it is and keeps feeding every
observability view (`vortex/observability/`) and the wall. Both convive: the
event log is what happened on a call, second by second; this database is
what the clinic's own system would keep about appointments and the calls
that touched them.

## Quick start

```bash
uv run pytest tests/test_database.py -q      # 11 tests, no key, no network
make confirmations                            # run the day-before job once (simulated calls)
make confirmations ARGS="--for 2026-09-25"    # as if today were that date
make confirmations ARGS="--force cancel:LCL-abc123"  # force one outcome, for a dry run
```

The file lives at `logs/vortex_product.db` by default (`VORTEX_PRODUCT_DB` to
override — see `.env.example`), next to `calls.jsonl` so both survive a
redeploy on the same mounted volume, the same reasoning
`vortex/line/voice_config.py` already applies to `voiceconfig.db`.

## Schema

### `calls`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | local surrogate key |
| `call_id` | TEXT, unique | the event log's own id — join key back to `logs/calls.jsonl` |
| `direction` | TEXT | `inbound` \| `outbound` |
| `purpose` | TEXT | `booking` \| `confirmation` \| `cancellation` \| `reschedule` \| `info` \| `other` |
| `language` | TEXT, indexed | ISO-639-1 (`es`/`en`/`ca`/...), detected from the caller's own words |
| `from_number` | TEXT | |
| `started_at` | TEXT, not null | ISO-8601, tz-aware |
| `duration_ms` | INTEGER | |
| `outcome` | TEXT | the contract's six actions, `book`/`cancel`/`reschedule`/`register`/`no_action`/`escalate`, plus `confirmed`/`no_answer` for an outbound confirmation call |
| `appointment_id` | TEXT, FK → `appointments.id`, nullable | the appointment this call touched, if any |

### `appointments`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | the platform's own appointment id for a cancel/reschedule target; a locally-minted `LCL-<hex>` id for a fresh booking (see below) |
| `status` | TEXT, not null | `scheduled` \| `confirmed` \| `cancelled` \| `completed` \| `no_show` |
| `patient_id`, `patient_name`, `patient_phone`, `patient_email` | TEXT | |
| `provider_id`, `provider_name`, `specialty_id`, `specialty_name` | TEXT | |
| `site_id`, `site_name` | TEXT | |
| `slot_start`, `slot_end` | TEXT, not null | ISO-8601, tz-aware |
| `insurer`, `appointment_type_id`, `appointment_type_name` | TEXT | |
| `reason` | TEXT | best-effort, the caller's own words at booking — never structured, never authoritative |
| `booking_call_id` | INTEGER, not null, FK → `calls.id` | see "Why `booking_call_id` is never NULL" |
| `confirmation_call_id` | INTEGER, nullable, FK → `calls.id` | set by the confirmation job, whatever the outcome |
| `created_at`, `updated_at` | TEXT, not null | |

Both indexes and the full `CREATE TABLE` live in `database/schema.py`,
migration 1 — every line has a comment explaining the choice next to it.
`language` is **not** a column on `appointments`: an appointment inherits it
by joining through `booking_call_id` (rule 5 of the brief), so it is never
duplicated or able to drift from the call it actually happened in.

## Design decisions worth knowing before you touch this

### Where an appointment's id comes from

The clinic API is read-only (`.claude/skills/submit-action`): a `book`
submission goes to the scoring platform, never to the clinic, so the clinic
never hands back an id for it. A fresh booking's `appointments.id` is
therefore minted locally: `LCL-<16 hex chars>`. A `cancel`/`reschedule`
submission's `appointment_id` **is** a real platform id (it came from
`/patients/{id}/appointments`, per the call contract), so those rows keep
that id as their primary key — no collision risk, the two id spaces never
overlap.

### Why `booking_call_id` is never NULL

Because the clinic never learns about a booking we only reported to the
scoring platform, **every cancel/reschedule this line ever submits targets
an appointment that already existed before any call of ours** — there is no
scenario in this challenge where a caller books through us and later calls
back to cancel that exact booking. So the normal path for a cancel/reschedule
is: look the appointment up in this database; if it is not there yet (the
common case — it predates this system), recover its slot/provider/patient
facts from the read-only clinic (which does know its own seed data) and
insert it now, with `booking_call_id` set to *this* — the discovering, not
booking — call. That is the one place the column's name is a small lie: it
answers "which call caused this database to first know about this
appointment", not literally always "which call booked it". Documented here
rather than hidden, and covered by
`test_cancellation_backfills_unseen_appointment_and_updates_status` in
`tests/test_database.py`.

If the caller cannot be identified at that point
(`CallMemory.identified_patient` is unset) or the clinic lookup fails, the
call is still recorded — only the appointment link is skipped (see
`test_cancellation_of_unknown_appointment_with_no_identified_patient_is_skipped`).
A telemetry gap, never a crashed call.

### The circular foreign key

`appointments.booking_call_id` points at `calls`, and `calls.appointment_id`
points back at `appointments` — SQLite does not defer constraint checking
the way Postgres can, so one of the two rows has to exist, unlinked, before
the other. The write path (`database/hooks.py`) always does it in this
order, one transaction:

1. `INSERT INTO calls (..., appointment_id = NULL)`
2. `INSERT INTO appointments (..., booking_call_id = <the call's id>)`
3. `UPDATE calls SET appointment_id = <the appointment's id> WHERE id = ...`

### `outcome` extends the contract's six actions by two

`calls.outcome` is `book`/`cancel`/`reschedule`/`register`/`no_action`/
`escalate` for an inbound call — the submit contract's own vocabulary — plus
`confirmed` and `no_answer`, which only an outbound confirmation call can
end in. A confirmation call that ends in a cancellation is still recorded as
`cancel`, the same word an inbound cancellation call uses, so an
appointment's own history reads the same regardless of which call cancelled
it.

### What this database does not model

`register`, `no-action` and `escalate` never touch an appointment, so
`database/hooks.py`'s `persist_submission` is a no-op for them — nothing to
write. A registration creates a *patient* on the scoring platform's side,
which is a different database this challenge does not ask for.

## The write hook

One entry point, `database.hooks.persist_submission(ctx, action, db_path=...)`,
called from `vortex/line/submit.py`'s `submit_action` — right after the
existing availability-cache invalidation, on the same condition
(`result.status in {"accepted", "duplicate"}`), **plus `"dry_run"`**: with no
`PLATFORM_API_KEY` (the default local setup — `make run` with no `.env`
keys) nothing the submit client sends is ever "accepted" by a real platform,
but the action is exactly as real locally as it would be against one, and
`make call` has to populate this database the same way a keyed deploy does.
Only a rejected, late or unknown-call submit means the action never really
happened.

The source is the submit's own `Action` — never an intermediate tool call —
so what lands here is exactly what was (or would have been) accepted, never
a plan the caller talked the agent out of.

Never raises into the call: every public function in `database/hooks.py`
catches broadly and logs. A database problem must not end or distort a call
any more than a broken `voiceconfig.db` read does.

## The confirmation job

Rule: every appointment scheduled for tomorrow gets exactly one outbound
confirmation call, and its result decides the appointment's status —
`confirmed`, `cancelled`, or unchanged (`scheduled`) if nobody answers.

`database/confirmations.py`:

- `db.appointments_due_for_confirmation` — status `scheduled`, slot tomorrow,
  no `confirmation_call_id` yet (the job's own idempotency: running it twice
  in a day does not double-dial).
- `ConfirmationCaller` — a `Protocol`, one async method, `call(appointment)
  -> ConfirmationResult`. **This is the interface the line implements once
  it can dial out.**
- `SimulatedConfirmationCaller` — today's only implementation. Always
  "confirmed" unless an appointment's id is listed in `force_outcome`, and
  still writes a full `call.started` → turns → `call.ended` → `call.summary`
  trace to `logs/calls.jsonl` through the ordinary `CallLog`, tagged with
  real `Settings.describe()` values (never `voice="demo"` or
  `clinic="synthetic-data"`, the markers
  `business_insights.is_real_call` excludes) — a confirmation call is
  genuine business activity, not an eval or demo artefact.
- `run_confirmations(conn, caller=...)` — the loop. Commits after every
  appointment, not once at the end, so one failed call does not roll back
  the ones already confirmed in the same run.

`database/scripts/run_confirmations.py` is the entry point today:
`make confirmations`. It is meant to be what a scheduler (cron, a periodic
task inside the line process, whatever the deploy ends up using) calls once
a day, not something a human runs by hand in production.

## What the line still has to build

There is **no outbound-calling capability anywhere in this codebase or the
call contract.** The platform only ever dials *into* `/ws`
(`.claude/skills/call-contract`); "outbound" elsewhere in the code
(`vortex/line/twilio.py`) means the direction of an audio frame inside an
inbound-initiated Media Stream, never a call this line places. Before
`ConfirmationCaller` can have a real implementation, the line needs:

1. A way to originate a call at all — Twilio Programmable Voice (or
   whatever the platform's own infrastructure offers, if anything) placing
   an outbound call to `appointment.patient_phone` and bridging it to a
   pipecat pipeline the same way an inbound Media Stream does today.
2. A short, fixed script/prompt for that call — read the appointment back,
   ask "confirm or cancel", handle "I need a different day" (today's rule 2
   only names confirm/cancel/no-answer; a reschedule-on-the-confirmation-
   call is a real product need this brief does not cover).
3. A retry policy for `no_answer` — today's job dials once and stops; a real
   product would try again later the same day or the next.
4. Deciding who calls `run_confirmations` and when — a daily cron, a
   NiceGUI-scheduled task in the board process, or a small standalone
   service. Nothing here assumes one over another; the interface
   (`ConfirmationCaller`, `run_confirmations`) is the same either way.

## Auxiliary cache (pre-existing, unrelated)

`database/scripts/refresh_slots.py` and `database/processed/` are a
separate, standalone cache of clinic availability by specialty — not wired
into anything, not part of this persistence layer, predates it. See the
comments in that script if you touch it.

## A natural next step for the wall (not built here)

Insights (`vortex/observability/business_insights.py`) and the Clinic View
currently know nothing about confirmation status — a `confirmed` vs. a
`scheduled-but-not-yet-confirmed` appointment look identical there today.
A `pending confirmations` count or a confirmation-rate tile would be a small,
useful addition once this ships, but it is a separate PR: this one adds the
data, not a new view over it.
