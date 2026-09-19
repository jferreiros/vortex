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

from database.models import (
    AppointmentRecord,
    AppointmentWithCalls,
    CallRecord,
    WallCancellationRecord,
)
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
            duration_ms = COALESCE(excluded.duration_ms, calls.duration_ms),
            outcome = excluded.outcome,
            appointment_id = COALESCE(excluded.appointment_id, calls.appointment_id)
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
    from database.remote import after_write

    after_write(conn, "calls", row, "call_id")
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
    row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_pk,)).fetchone()
    if row is not None:
        from database.remote import after_write

        after_write(conn, "calls", row, "call_id")


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
    from database.remote import after_write

    after_write(conn, "appointments", row, "id")
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
    from database.remote import after_write

    after_write(conn, "appointments", row, "id")
    return AppointmentRecord.from_row(row)


def set_confirmation_call(conn: sqlite3.Connection, appointment_id: str, call_pk: int) -> None:
    conn.execute(
        "UPDATE appointments SET confirmation_call_id = ?, updated_at = ? WHERE id = ?",
        (call_pk, now_iso(), appointment_id),
    )
    row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    if row is not None:
        from database.remote import after_write

        after_write(conn, "appointments", row, "id")


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


#: Statuses that still occupy a slot in the diary. ``cancelled`` frees it, and
#: ``no_show``/``completed`` are about a visit that already happened, so the
#: board's forward-looking agenda asks for these two.
OPEN_STATUSES: tuple[str, ...] = ("scheduled", "confirmed")


def list_appointments(
    conn: sqlite3.Connection,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    statuses: tuple[str, ...] = OPEN_STATUSES,
) -> list[AppointmentRecord]:
    """Appointments in a date window, oldest slot first.

    The window is compared on ``substr(slot_start, 1, 10)`` rather than by
    parsing: ``slot_start`` is stored as tz-aware ISO-8601 with an explicit
    offset, and every row carries Europe/Madrid's, so the leading date is
    already the local calendar day the board draws.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if statuses:
        clauses.append(f"status IN ({', '.join('?' for _ in statuses)})")
        params.extend(statuses)
    if date_from is not None:
        clauses.append("substr(slot_start, 1, 10) >= ?")
        params.append(date_from.isoformat())
    if date_to is not None:
        clauses.append("substr(slot_start, 1, 10) <= ?")
        params.append(date_to.isoformat())
    from database.remote import mirrors_product, select

    if mirrors_product(conn):
        remote_rows = select("appointments", {"order": "slot_start"})
        if remote_rows:
            records = [AppointmentRecord.from_row(row) for row in remote_rows]  # type: ignore[arg-type]
            if statuses:
                records = [r for r in records if r.status in statuses]
            if date_from is not None:
                records = [r for r in records if r.slot_start[:10] >= date_from.isoformat()]
            if date_to is not None:
                records = [r for r in records if r.slot_start[:10] <= date_to.isoformat()]
            return records
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM appointments {where} ORDER BY slot_start",  # noqa: S608 - clauses are this function's own literals
        params,
    ).fetchall()
    return [AppointmentRecord.from_row(row) for row in rows]


def call_id_by_appointment(conn: sqlite3.Connection) -> dict[str, str]:
    """``appointments.id`` -> the event log's own ``call_id`` for the call that
    booked it — what a screen needs to link a visit back to its transcript,
    since ``booking_call_id`` is this database's integer key, not the log's."""
    rows = conn.execute(
        """
        SELECT a.id AS appointment_id, c.call_id AS call_id
        FROM appointments a
        JOIN calls c ON c.id = a.booking_call_id
        """
    ).fetchall()
    from database.remote import mirrors_product, select

    if mirrors_product(conn):
        appts = select("appointments", {"select": "id,booking_call_id"})
        calls = select("calls", {"select": "id,call_id"})
        if appts is not None and calls is not None:
            by_pk = {int(c["id"]): str(c["call_id"]) for c in calls}
            return {
                str(a["id"]): by_pk[int(a["booking_call_id"])]
                for a in appts
                if a.get("booking_call_id") is not None and int(a["booking_call_id"]) in by_pk
            }
    return {row["appointment_id"]: row["call_id"] for row in rows}


# ---------------------------------------------------------------------------
# wall cancellations (the board's Horarios page cancelling by hand)
# ---------------------------------------------------------------------------
#
# This is where the control centre's cancel buttons connect: the FastAPI
# routes in ``vortex/observability/live.py`` (``/api/wall/appointments/cancel``
# and ``/api/wall/agenda/cancel[-preview]``) are the only callers. A wall
# cancellation is not a call, so it writes no ``calls`` row — one
# ``wall_cancellations`` row per slot, and when the appointment also exists
# in ``appointments`` its ``status`` flips to ``cancelled``, the same word a
# phone cancellation writes through ``database/hooks.py``.


def insert_wall_cancellation(
    conn: sqlite3.Connection,
    *,
    provider_id: str,
    site_id: str,
    slot_start: str,
    appointment_id: str | None = None,
    patient_name: str | None = None,
    provider_name: str | None = None,
) -> WallCancellationRecord:
    """Record one hand-cancelled diary slot. ``slot_start`` is ISO-8601 with
    an explicit offset; the caller normalises to the minute."""
    row = conn.execute(
        """
        INSERT INTO wall_cancellations
            (provider_id, site_id, slot_start,
             appointment_id, patient_name, provider_name, cancelled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        (
            provider_id,
            site_id,
            slot_start,
            appointment_id,
            patient_name,
            provider_name,
            now_iso(),
        ),
    ).fetchone()
    from database.remote import after_write

    after_write(conn, "wall_cancellations", row, "id")
    return WallCancellationRecord.from_row(row)


def list_wall_cancellations(conn: sqlite3.Connection) -> list[WallCancellationRecord]:
    """Every hand-cancelled slot — the set the agenda filters out per request."""
    from database.remote import mirrors_product, select

    if mirrors_product(conn):
        remote_rows = select("wall_cancellations", {"order": "slot_start"})
        if remote_rows:
            return [WallCancellationRecord.from_row(row) for row in remote_rows]  # type: ignore[arg-type]
    rows = conn.execute("SELECT * FROM wall_cancellations ORDER BY slot_start").fetchall()
    return [WallCancellationRecord.from_row(row) for row in rows]


def cancel_appointment_rows(
    conn: sqlite3.Connection, *, provider_id: str, day_from: date, day_to: date
) -> list[str]:
    """Batch path: flip every live ``appointments`` row of this doctor whose
    slot falls inside [``day_from``, ``day_to``] to ``cancelled``. Returns the
    ids it touched. Rows this database never knew are unaffected by design —
    their cancellation lives only in ``wall_cancellations``."""
    rows = conn.execute(
        """
        UPDATE appointments SET status = 'cancelled', updated_at = ?
        WHERE provider_id = ?
          AND substr(slot_start, 1, 10) BETWEEN ? AND ?
          AND status IN ('scheduled', 'confirmed')
        RETURNING id
        """,
        (now_iso(), provider_id, day_from.isoformat(), day_to.isoformat()),
    ).fetchall()
    ids = [str(row["id"]) for row in rows]
    from database.remote import after_write

    for appointment_id in ids:
        synced = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        if synced is not None:
            after_write(conn, "appointments", synced, "id")
    return ids


def cancel_appointment_row(
    conn: sqlite3.Connection,
    *,
    appointment_id: str | None = None,
    provider_id: str | None = None,
    slot_start: str | None = None,
) -> str | None:
    """Single path: flip one live ``appointments`` row to ``cancelled`` and
    return its id — by ``appointment_id`` when there is one, else by the
    doctor-and-minute the slot key names. ``None`` when nothing live matched."""
    if appointment_id:
        rows = conn.execute(
            """
            UPDATE appointments SET status = 'cancelled', updated_at = ?
            WHERE id = ? AND status IN ('scheduled', 'confirmed')
            RETURNING id
            """,
            (now_iso(), appointment_id),
        ).fetchall()
        if rows:
            appointment_id = str(rows[0]["id"])
            synced = conn.execute(
                "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
            if synced is not None:
                from database.remote import after_write

                after_write(conn, "appointments", synced, "id")
            return appointment_id
    if provider_id and slot_start:
        rows = conn.execute(
            """
            UPDATE appointments SET status = 'cancelled', updated_at = ?
            WHERE provider_id = ? AND substr(slot_start, 1, 16) = ?
              AND status IN ('scheduled', 'confirmed')
            RETURNING id
            """,
            (now_iso(), provider_id, slot_start[:16]),
        ).fetchall()
        if rows:
            appointment_id = str(rows[0]["id"])
            synced = conn.execute(
                "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
            if synced is not None:
                from database.remote import after_write

                after_write(conn, "appointments", synced, "id")
            return appointment_id
    return None


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
