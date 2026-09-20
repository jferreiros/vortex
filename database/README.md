# database/

The product's own database: `appointments` and `calls`, answering "what did
we book, and which call did it". One store, hosted Postgres on Supabase,
reached over PostgREST. No file, no SQLite, no local fallback — the line and
the board read and write the same rows, which is the only way the wall can
show a booking a call made two seconds ago on a different process.

## Quick start

```bash
make supabase-migrate                         # apply database/supabase/migrations/*.sql
uv run python database/scripts/load_seed.py   # the demo's starting diary
uv run pytest tests/test_database.py -q       # skips without Supabase keys
make confirmations                            # run the day-before job once (simulated calls)
make confirmations ARGS="--for 2026-09-25"    # as if today were that date
make confirmations ARGS="--force cancel:LCL-abc123"  # force one outcome, for a dry run
```

Two different environment variables, and mixing them up is the usual first
mistake:

| Variable | What it is | Who uses it |
| --- | --- | --- |
| `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` | the PostgREST origin and its server-side key | everything at runtime (`database/remote.py`) |
| `SUPABASE_DB_URL` | the **direct Postgres URI** | only `database/supabase/migrate.py` and `load_seed.py` |

`SUPABASE_DB_URL` comes from the Supabase Dashboard → Project Settings →
Database → Connection string → **URI**. DDL cannot go through PostgREST, so
migrations are the one thing that opens a real connection, with psycopg.

The service-role key is server-side only. It never reaches a browser: the
wall gets at these tables through the board's own `/api/wall` routes.

## Migrations

`database/supabase/migrations/` holds numbered SQL files, applied in lexical
order by `make supabase-migrate` (`uv run python -m database.supabase.migrate`).

- One transaction per file. The file's id (its name without `.sql`) is
  inserted into `public.schema_migrations` inside that same transaction, so a
  file either lands whole and is recorded, or lands not at all and is retried.
- An id already in `schema_migrations` is skipped.
- **Never edit `0001_init.sql` once it has been applied.** A database that
  already recorded `0001_init` will never read that file again, so the change
  would exist on your machine and nowhere else. A later change is a new file:
  `0002_<name>.sql`.
- `--dry-run` lists what is pending and changes nothing.

## Schema

`database/supabase/migrations/0001_init.sql` is the source of truth and every
column carries the comment explaining it. The shape:

### `calls`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigint identity PK | local surrogate key |
| `call_id` | text, unique | the event log's own id — the join key back to a call's transcript |
| `direction` | text | `inbound` \| `outbound` |
| `purpose` | text | `booking` \| `confirmation` \| `cancellation` \| `reschedule` \| `info` \| `other` |
| `language` | text, indexed | ISO-639-1 (`es`/`en`/`ca`/...), detected from the caller's own words |
| `from_number` | text | |
| `started_at` | text, not null | ISO-8601, tz-aware |
| `duration_ms` | integer | |
| `outcome` | text | the contract's six actions, plus `confirmed`/`no_answer` for an outbound confirmation call |
| `appointment_id` | text | the appointment this call touched, if any |
| `motivo` | text | why an *outbound* call was placed; NULL for inbound |
| `transcript`, `detail` | text | filled in later, when a queued outbound call resolves |

### `appointments`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | the platform's own appointment id for a cancel/reschedule target; a locally-minted `LCL-<hex>` id for a fresh booking (see below) |
| `status` | text, not null | `scheduled` \| `confirmed` \| `cancelled` \| `completed` \| `no_show` |
| `patient_id`, `patient_name`, `patient_phone`, `patient_email` | text | |
| `provider_id`, `provider_name`, `specialty_id`, `specialty_name` | text | |
| `site_id`, `site_name` | text | |
| `slot_start`, `slot_end` | text, not null | ISO-8601, tz-aware |
| `insurer`, `appointment_type_id`, `appointment_type_name` | text | |
| `reason` | text | best-effort, the caller's own words at booking — never structured, never authoritative |
| `booking_call_id` | bigint, not null | see "Why `booking_call_id` is never NULL" |
| `confirmation_call_id` | bigint | set by the confirmation job, whatever the outcome |
| `created_at`, `updated_at` | text, not null | |
| `rebooked_from_id` | text | the appointment this one replaces, when a cancellation freed the slot |

`language` is **not** a column on `appointments`: an appointment inherits it
by joining through `booking_call_id`, so it is never duplicated or able to
drift from the call it actually happened in.

The other tables 0001 creates: `call_events` (the call event log, plus the
`call_events_for_window` function Home and Insights read it through),
`wall_cancellations`, `rebooking_requests`, `clinic_settings`,
`wall_documents`, `suggestion_rejections`, `voiceconfig`, `personalities`.
RLS is on everywhere and there are no public policies — only the service-role
key can read or write.

## The API

Every function in `database/db.py` takes no connection. There is nothing to
open, so there is nothing to share between calls, which is CLAUDE.md's rule 3
for free.

```python
from database import db

call = db.insert_call(call_id="CA123", direction="inbound", purpose="booking", ...)
db.insert_appointment(id="LCL-...", booking_call_id=call.id, ...)
db.link_call_to_appointment(call.id, "LCL-...")
```

When Supabase is not configured (`remote.enabled()` is false), **reads return
empty or `None`** and **writes raise `RuntimeError("supabase not
configured")`**. Callers decide which of those is fatal: `database/hooks.py`
catches it and logs, because a telemetry write must never end a scoring call.

`database/remote.py` is the whole transport: `enabled()`, `select`, `upsert`,
`safe_upsert`, `update`, `delete`, `count`. Reads swallow failures and return
`None`; writes raise; `safe_upsert` is the one that logs instead.

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
back to cancel that same booking. So the normal path for a cancel/reschedule
is: look the appointment up here; if it is not there yet (the common case —
it predates this system), recover its slot/provider/patient facts from the
read-only clinic (which does know its own seed data) and insert it now, with
`booking_call_id` set to *this* — the discovering, not booking — call. That
is the one place the column's name is a small lie: it answers "which call
made this database first know about this appointment".

If the caller cannot be identified at that point
(`CallMemory.identified_patient` is unset) or the clinic lookup fails, the
call is still recorded — only the appointment link is skipped. A telemetry
gap, never a crashed call.

### The circular reference, and why neither side is a foreign key

`appointments.booking_call_id` names a `calls` row, and `calls.appointment_id`
names an `appointments` row. Neither is declared as a foreign key: one of the
two rows always has to exist before the other, and a plain column keeps the
write path a straight line instead of a deferred-constraint dance. The order
`database/hooks.py` writes in:

1. `insert_call(...)` — `appointment_id` left NULL
2. `insert_appointment(..., booking_call_id=<the call's id>)`
3. `link_call_to_appointment(<the call's id>, <the appointment's id>)`

That used to be "three statements, one transaction" against SQLite. On
Postgres it is three requests, and each one is complete on its own: a run
that dies between 2 and 3 leaves an appointment whose call is known and a
call whose appointment is not yet linked — readable, not corrupt.

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

One entry point, `database.hooks.persist_submission(ctx, action)`, called
from `vortex/line/submit.py`'s `submit_action` — right after the existing
availability-cache invalidation, on the same condition (`result.status in
{"accepted", "duplicate"}`), **plus `"dry_run"`**: with no `PLATFORM_API_KEY`
nothing the submit client sends is ever "accepted" by a real platform, but
the action is exactly as real locally as it would be against one, and
`make call` has to populate this database the same way a keyed deploy does.

The source is the submit's own `Action` — never an intermediate tool call —
so what lands here is exactly what was (or would have been) accepted, never
a plan the caller talked the agent out of.

Never raises into the call. It always *attempts* the write, including with
no Supabase configured; that failure is logged loudly, not skipped quietly.
`persist_submission` still accepts a `db_path` keyword and ignores it, so an
old call site cannot turn into a `TypeError` mid-call.

## The confirmation job

Rule: every appointment scheduled for tomorrow gets exactly one outbound
confirmation call, and its result decides the appointment's status —
`confirmed`, `cancelled`, or unchanged (`scheduled`) if nobody answers.

`database/confirmations.py`:

- `db.appointments_due_for_confirmation(on_date=...)` — status `scheduled`,
  slot that day, no `confirmation_call_id` yet (the job's own idempotency:
  running it twice in a day does not double-dial).
- `ConfirmationCaller` — a `Protocol`, one async method, `call(appointment)
  -> ConfirmationResult`. **This is the interface the line implements once
  it can dial out.**
- `SimulatedConfirmationCaller` — today's only implementation. Always
  "confirmed" unless an appointment's id is listed in `force_outcome`, and
  still writes a full `call.started` → turns → `call.ended` → `call.summary`
  trace through the ordinary `CallLog`, tagged with real
  `Settings.describe()` values (never `voice="demo"` or
  `clinic="synthetic-data"`, the markers `business_insights.is_real_call`
  excludes) — a confirmation call is genuine business activity, not an eval
  or demo artefact.
- `run_confirmations(caller=...)` — the loop. Each appointment is written as
  it resolves, so one failed call cannot undo the ones already confirmed.

`database/scripts/run_confirmations.py` is the entry point today:
`make confirmations`. It is meant to be what a scheduler calls once a day,
not something a human runs by hand in production.

## Seeds

`database/seed/*.sql` is the diary the demo starts from — the slots the
control centre has already cancelled and the rebooking callbacks they left
behind. Data only, plain Postgres, written to be re-runnable
(`on conflict do nothing` / `where not exists`), so loading twice is not
destructive and a live store is never silently wiped. Load with
`uv run python database/scripts/load_seed.py`, after the migrations.

## What the line still has to build

There is **no outbound-calling capability anywhere in this codebase or the
call contract.** The platform only ever dials *into* `/ws`
(`.claude/skills/call-contract`). Before `ConfirmationCaller` can have a real
implementation, the line needs:

1. A way to originate a call at all — Twilio Programmable Voice placing an
   outbound call to `appointment.patient_phone` and bridging it to a pipecat
   pipeline the way an inbound Media Stream does today.
2. A short, fixed script for that call — read the appointment back, ask
   "confirm or cancel", handle "I need a different day".
3. A retry policy for `no_answer` — today's job dials once and stops.
4. Deciding who calls `run_confirmations` and when — a daily cron, a task in
   the board process, or a small standalone service. The interface is the
   same either way.
