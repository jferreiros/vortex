-- Vortex product-data seed.
-- Regenerate: run the board, cancel visits from Horarios, then dump again:
--   python -c "import sqlite3; print(chr(10).join(sqlite3.connect('logs/vortex_product.db').iterdump()))"
-- Load into place: python database/scripts/load_seed.py [--replace]

BEGIN TRANSACTION;
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
CREATE TABLE wall_cancellations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id     TEXT NOT NULL,
    site_id         TEXT NOT NULL,
    -- ISO-8601, Europe/Madrid, minute precision — the BookingKey third leg.
    slot_start      TEXT NOT NULL,
    -- The clinic's own appointment id when the visit carried one (seed/pack
    -- rows do; a booking replayed from the log may not). Audit only.
    appointment_id  TEXT,
    -- Display hints for the audit trail — never authoritative, never joined.
    patient_name    TEXT,
    provider_name   TEXT,
    cancelled_at    TEXT NOT NULL
);
INSERT INTO "wall_cancellations" VALUES(1,'PR04','centro','2026-09-22T11:30:00+02:00',NULL,'Ignacio Vázquez Moreno','Dra. Iglesias','2026-09-19T18:29:22.717+00:00');
INSERT INTO "wall_cancellations" VALUES(2,'PR04','centro','2026-09-23T11:30:00+02:00',NULL,'Josefa Domínguez Navarro','Dra. Iglesias','2026-09-19T18:29:22.718+00:00');
INSERT INTO "wall_cancellations" VALUES(3,'PR04','centro','2026-09-24T11:30:00+02:00',NULL,'Josefa Domínguez Navarro','Dra. Iglesias','2026-09-19T18:29:22.718+00:00');
INSERT INTO "wall_cancellations" VALUES(4,'PR03','sur','2026-09-21T09:00:00+02:00',NULL,'Ignacio Vázquez Moreno','Dra. Sáenz','2026-09-19T18:29:52.818+00:00');
CREATE INDEX idx_calls_language ON calls(language);
CREATE INDEX idx_calls_appointment_id ON calls(appointment_id);
CREATE INDEX idx_calls_purpose ON calls(purpose);
CREATE INDEX idx_appointments_patient_id ON appointments(patient_id);
CREATE INDEX idx_appointments_slot_start ON appointments(slot_start);
CREATE INDEX idx_appointments_status ON appointments(status);
CREATE INDEX idx_wall_cancellations_slot
    ON wall_cancellations(provider_id, site_id, slot_start);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('wall_cancellations',4);
COMMIT;
PRAGMA user_version = 2;
