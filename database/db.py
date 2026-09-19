"""Connection handling and every query the persistence layer runs.

One SQLite file, opened fresh per call — short-lived connections, no handle
shared across requests or asyncio tasks, so correctness under concurrency
rests entirely on SQLite's own file locking: WAL mode (readers never block
the writer) plus a busy timeout (a write that meets a momentary lock retries
instead of raising). ``Run All`` opens ten sockets at once and problem 2
opens twenty (CLAUDE.md's own concurrency rule) — this is what keeps two
bookings landing in the same second from corrupting each other.

Deliberately independent of ``vortex``: nothing here imports it, so this
layer is testable and reusable on its own. The path is the caller's choice
(``vortex/settings.py``'s ``product_db_path`` for the app; ``:memory:`` or a
tmp file for tests).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from database.models import AppointmentRecord, AppointmentWithCalls, CallRecord
from database.schema import migrate

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "vortex.db"

#: Seconds SQLite retries a write against a momentarily locked file before
#: raising ``sqlite3.OperationalError``.
_BUSY_TIMEOUT_S = 5.0


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """One migrated, row-returning, foreign-key-enforcing connection.

    ``migrate`` runs on every connect — idempotent (``schema.migrate``), so
    there is no separate "first run" step to remember or forget in a fresh
    environment or a test's tmp file.
    """
    db_path = Path(path) if path else DEFAULT_DB_PATH
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=_BUSY_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


@contextmanager
def connection(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """A connection that commits on a clean exit, rolls back on an
    exception, and always closes — the shape every write in this module
    other than ``connect`` itself is meant to be called under."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# calls
# ---------------------------------------------------------------------------


def insert_call(
    conn: sqlite3.Connection,
    *,
    call_id: str,
    direction: str,
    purpose: str,
    started_at: str,
    language: str | None = None,
    from_number: str | None = None,
    duration_ms: int | None = None,
    outcome: str | None = None,
    appointment_id: str | None = None,
) -> CallRecord:
    """Insert one ``calls`` row, or update it in place if ``call_id`` was
    already seen — a retried identical submit (the platform's own 409
    "duplicate, treat as success") must update the same row, never mint a
    second one for the same call.
    """
    row = conn.execute(
        """
        INSERT INTO calls
            (call_id, direction, purpose, language, from_number,
             started_at, duration_ms, outcome, appointment_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(call_id) DO UPDATE SET
            purpose = excluded.purpose,
            language = excluded.language,
            duration_ms = excluded.duration_ms,
            outcome = excluded.outcome,
            appointment_id = excluded.appointment_id
        RETURNING *
        """,
        (
            call_id,
            direction,
            purpose,
            language,
            from_number,
            started_at,
            duration_ms,
            outcome,
            appointment_id,
        ),
    ).fetchone()
    return CallRecord.from_row(row)


def get_call(conn: sqlite3.Connection, call_pk: int) -> CallRecord | None:
    row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_pk,)).fetchone()
    return CallRecord.from_row(row) if row else None


def get_call_by_call_id(conn: sqlite3.Connection, call_id: str) -> CallRecord | None:
    """The row for the event log's own id — how a repeated submit on the
    same call finds what it already wrote."""
    row = conn.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
    return CallRecord.from_row(row) if row else None


def link_call_to_appointment(conn: sqlite3.Connection, call_pk: int, appointment_id: str) -> None:
    conn.execute("UPDATE calls SET appointment_id = ? WHERE id = ?", (appointment_id, call_pk))


# ---------------------------------------------------------------------------
# appointments
# ---------------------------------------------------------------------------


def insert_appointment(
    conn: sqlite3.Connection,
    *,
    id: str,  # noqa: A002 - matches the column name; this is a row constructor
    booking_call_id: int,
    patient_id: str,
    slot_start: str,
    slot_end: str,
    status: str = "scheduled",
    patient_name: str | None = None,
    patient_phone: str | None = None,
    patient_email: str | None = None,
    provider_id: str | None = None,
    provider_name: str | None = None,
    specialty_id: str | None = None,
    specialty_name: str | None = None,
    site_id: str | None = None,
    site_name: str | None = None,
    insurer: str | None = None,
    appointment_type_id: str | None = None,
    appointment_type_name: str | None = None,
    reason: str | None = None,
) -> AppointmentRecord:
    """Insert one fresh ``appointments`` row. ``booking_call_id`` must
    already exist in ``calls`` — insert that row first (see
    ``database/hooks.py`` for the three-statement order this needs, spelled
    out in ``schema.py``'s migration-1 comment)."""
    ts = now_iso()
    row = conn.execute(
        """
        INSERT INTO appointments (
            id, status, patient_id, patient_name, patient_phone, patient_email,
            provider_id, provider_name, specialty_id, specialty_name,
            site_id, site_name, slot_start, slot_end, insurer,
            appointment_type_id, appointment_type_name, reason,
            booking_call_id, confirmation_call_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        RETURNING *
        """,
        (
            id,
            status,
            patient_id,
            patient_name,
            patient_phone,
            patient_email,
            provider_id,
            provider_name,
            specialty_id,
            specialty_name,
            site_id,
            site_name,
            slot_start,
            slot_end,
            insurer,
            appointment_type_id,
            appointment_type_name,
            reason,
            booking_call_id,
            ts,
            ts,
        ),
    ).fetchone()
    return AppointmentRecord.from_row(row)


def get_appointment(conn: sqlite3.Connection, appointment_id: str) -> AppointmentRecord | None:
    row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    return AppointmentRecord.from_row(row) if row else None


def update_appointment(
    conn: sqlite3.Connection, appointment_id: str, **fields: Any
) -> AppointmentRecord:
    """Patch any subset of columns (never ``id`` or ``booking_call_id``,
    which never change once written) and bump ``updated_at``."""
    fields = dict(fields)
    fields["updated_at"] = now_iso()
    columns = ", ".join(f"{key} = ?" for key in fields)
    row = conn.execute(
        f"UPDATE appointments SET {columns} WHERE id = ? RETURNING *",  # noqa: S608 - keys are this module's own kwargs, never user input
        (*fields.values(), appointment_id),
    ).fetchone()
    if row is None:
        raise KeyError(f"no appointment {appointment_id!r} to update")
    return AppointmentRecord.from_row(row)


def set_confirmation_call(conn: sqlite3.Connection, appointment_id: str, call_pk: int) -> None:
    conn.execute(
        "UPDATE appointments SET confirmation_call_id = ?, updated_at = ? WHERE id = ?",
        (call_pk, now_iso(), appointment_id),
    )


def appointments_due_for_confirmation(
    conn: sqlite3.Connection, *, on_date: date
) -> list[AppointmentRecord]:
    """Scheduled appointments whose slot falls on ``on_date`` and that have
    not already had a confirmation call placed — the confirmation job's own
    idempotency: running it twice for the same day must not double-dial."""
    day = on_date.isoformat()
    rows = conn.execute(
        """
        SELECT * FROM appointments
        WHERE status = 'scheduled'
          AND confirmation_call_id IS NULL
          AND substr(slot_start, 1, 10) = ?
        ORDER BY slot_start
        """,
        (day,),
    ).fetchall()
    return [AppointmentRecord.from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# navigating both ways
# ---------------------------------------------------------------------------


def appointment_with_calls(
    conn: sqlite3.Connection, appointment_id: str
) -> AppointmentWithCalls | None:
    appt = get_appointment(conn, appointment_id)
    if appt is None:
        return None
    booking_call = get_call(conn, appt.booking_call_id)
    assert booking_call is not None, "booking_call_id is NOT NULL and FK-enforced"
    confirmation_call = (
        get_call(conn, appt.confirmation_call_id) if appt.confirmation_call_id else None
    )
    return AppointmentWithCalls(
        appointment=appt, booking_call=booking_call, confirmation_call=confirmation_call
    )


def call_with_appointment(
    conn: sqlite3.Connection, call_pk: int
) -> tuple[CallRecord, AppointmentRecord | None] | None:
    call = get_call(conn, call_pk)
    if call is None:
        return None
    appt = get_appointment(conn, call.appointment_id) if call.appointment_id else None
    return call, appt
