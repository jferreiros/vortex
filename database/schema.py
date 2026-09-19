"""Versioned SQLite migrations for the product database.

Each entry in ``MIGRATIONS`` is one immutable step, applied at most once and
in order, tracked with SQLite's own ``PRAGMA user_version`` — no extra
bookkeeping table, no third-party migration framework: the repo has neither
today and this is the same "plain stdlib, one small file" shape
``vortex/line/voice_config.py`` already uses for its own SQLite file.

Adding a change later means appending a new string to ``MIGRATIONS``, never
editing an old one — a database that already ran migration 1 must not see
its SQL change under it.
"""

from __future__ import annotations

import sqlite3

#: Migration 1: the initial schema.
#:
#: ``calls`` and ``appointments`` reference each other (a call points at the
#: appointment it touched; an appointment points at the calls that booked and
#: confirmed it), so neither table can carry a ``NOT NULL`` foreign key to
#: the other at CREATE time — one of the two rows must exist first. SQLite
#: does not defer constraint checking the way Postgres can, so the write
#: path (``database/hooks.py``) inserts the call row first with
#: ``appointment_id`` left ``NULL``, inserts the appointment row with the
#: real ``booking_call_id``, then updates the call row's ``appointment_id``
#: — three statements, one transaction, described in ``db.record_booking``.
_MIGRATION_1 = """
CREATE TABLE calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The event log's own call_id (start.callSid for an inbound call; a
    -- synthesised id for a simulated outbound one) — the join key back to
    -- logs/calls.jsonl for a full transcript/tool trace of this call.
    call_id       TEXT NOT NULL UNIQUE,
    direction     TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    purpose       TEXT NOT NULL CHECK (
                      purpose IN (
                          'booking', 'confirmation', 'cancellation',
                          'reschedule', 'info', 'other'
                      )
                  ),
    -- ISO-639-1: es, en, ca, gl, eu. Nullable — an outbound call with no
    -- caller turn to detect from (a confirmation nobody answered) carries
    -- none. Indexed: the challenge scores a languages problem, and "which
    -- language did this outcome happen in" is a real analysis dimension.
    language      TEXT,
    from_number   TEXT,
    started_at    TEXT NOT NULL,
    duration_ms   INTEGER,
    -- The contract's own six actions for an inbound call (book / cancel /
    -- reschedule / register / no_action / escalate), extended with the two
    -- results only an outbound confirmation call can end in: confirmed (the
    -- patient confirmed) and no_answer (nobody picked up). A cancellation
    -- reached *through* a confirmation call is still 'cancel' — the same
    -- word an inbound cancellation call uses — because the appointment's
    -- own history should read the same regardless of which call cancelled it.
    outcome       TEXT CHECK (
                      outcome IN (
                          'book', 'cancel', 'reschedule', 'register',
                          'no_action', 'escalate', 'confirmed', 'no_answer'
                      )
                  ),
    -- The appointment this call touched, if any. NULL for a call that never
    -- reached a booking/cancel/reschedule/confirmation outcome.
    appointment_id TEXT REFERENCES appointments(id)
);
CREATE INDEX idx_calls_language ON calls(language);
CREATE INDEX idx_calls_appointment_id ON calls(appointment_id);
CREATE INDEX idx_calls_purpose ON calls(purpose);

CREATE TABLE appointments (
    -- The platform's own appointment_id for a cancel/reschedule target (the
    -- read-only clinic already knows it); a locally-minted "LCL-<hex>" id
    -- for one this call just booked, since the clinic is read-only and never
    -- hands back an id for a booking we only reported (see
    -- database/README.md, "Where an appointment's id comes from").
    id                     TEXT PRIMARY KEY,
    status                 TEXT NOT NULL DEFAULT 'scheduled' CHECK (
                               status IN (
                                   'scheduled', 'confirmed', 'cancelled',
                                   'completed', 'no_show'
                               )
                           ),
    patient_id             TEXT NOT NULL,
    patient_name           TEXT,
    patient_phone          TEXT,
    patient_email          TEXT,
    provider_id            TEXT,
    provider_name          TEXT,
    specialty_id           TEXT,
    specialty_name         TEXT,
    site_id                TEXT,
    site_name              TEXT,
    -- Timezone-aware ISO-8601, same rule the rest of the contract holds
    -- every slot to.
    slot_start             TEXT NOT NULL,
    slot_end               TEXT NOT NULL,
    insurer                TEXT,
    appointment_type_id    TEXT,
    appointment_type_name  TEXT,
    -- Best-effort, from the caller's own words at booking time — there is no
    -- structured "chief complaint" field in the submit contract. Never
    -- authoritative; never shown as if it were.
    reason                 TEXT,
    -- Rule: every appointment in this database was found through some call,
    -- and that call is never optional, so this is NOT NULL. See
    -- database/README.md, "Why booking_call_id is never NULL", for the one
    -- case (a cancel/reschedule of an appointment this database has never
    -- seen before) where the "booking" call is really the discovering call.
    booking_call_id        INTEGER NOT NULL REFERENCES calls(id),
    -- Set the day before the appointment by the confirmation job
    -- (database/confirmations.py). NULL until then, and forever on an
    -- appointment cancelled or rescheduled before that job ran.
    confirmation_call_id   INTEGER REFERENCES calls(id),
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE INDEX idx_appointments_patient_id ON appointments(patient_id);
CREATE INDEX idx_appointments_slot_start ON appointments(slot_start);
CREATE INDEX idx_appointments_status ON appointments(status);
"""

#: Append, never edit — see the module docstring.
MIGRATIONS: tuple[str, ...] = (_MIGRATION_1,)


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` to the latest schema. Returns the version applied to.

    Idempotent: a connection already at the latest version runs no SQL.
    Safe to call on every connect, the same way Django/Rails migrations are
    meant to run on deploy — there is no separate "first run" path to forget.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for i in range(current, len(MIGRATIONS)):
        conn.executescript(MIGRATIONS[i])
        conn.execute(f"PRAGMA user_version = {i + 1}")
    conn.commit()
    return len(MIGRATIONS)
