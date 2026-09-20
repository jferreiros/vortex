"""Every query the persistence layer runs, over PostgREST.

There is one store: the hosted Postgres behind ``SUPABASE_URL``. No file, no
connection to open, no handle to share — which is what makes rule 3 ("no
shared state between calls") free here: ``Run All`` opens ten sockets at once
and problem 2 opens twenty, and each one issues its own stateless HTTPS
request. Concurrency is Postgres's problem, where it belongs.

Every public function in this module therefore takes no connection. The
schema it expects lives in ``database/supabase/migrations/`` and is applied
once with ``make supabase-migrate``.

When Supabase is not configured (``remote.enabled()`` is false) there is
nowhere to go: reads return empty/``None`` and writes raise
``RuntimeError("supabase not configured")``. Callers decide whether that is
fatal — ``database/hooks.py``, which must never take a call down, swallows it
and logs.

Deliberately independent of ``vortex``: nothing here imports it, so this
layer is testable and reusable on its own.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from database import remote
from database.models import (
    AppointmentRecord,
    AppointmentWithCalls,
    CallRecord,
    WallCancellationRecord,
)

log = logging.getLogger("database.db")


class NotConfigured(RuntimeError):
    """Raised by every write when there is no Supabase to write to."""

    def __init__(self) -> None:
        super().__init__("supabase not configured")


def _require_remote() -> None:
    if not remote.enabled():
        raise NotConfigured


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _one(rows: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# calls
# ---------------------------------------------------------------------------


def insert_call(
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
    motivo: str | None = None,
) -> CallRecord:
    """Insert one ``calls`` row, or update it in place if ``call_id`` was
    already seen — a retried identical submit (the platform's own 409
    "duplicate, treat as success") must update the same row, never mint a
    second one for the same call.

    ``duration_ms``, ``appointment_id`` and ``motivo`` are only ever filled
    in, never blanked: a second write that does not know them keeps whatever
    the first one wrote (what the old SQL did with ``COALESCE``).

    ``motivo`` is the outbound-call reason (confirmacion / recordatorio /
    reprogramacion / seguimiento / call_now); leave it ``None`` for an
    inbound call.
    """
    _require_remote()
    existing = _one(remote.select("calls", {"call_id": f"eq.{call_id}", "limit": "1"}))
    payload: dict[str, Any] = {
        "call_id": call_id,
        "direction": direction,
        "purpose": purpose,
        "language": language,
        "from_number": from_number,
        "started_at": started_at,
        "duration_ms": duration_ms,
        "outcome": outcome,
        "appointment_id": appointment_id,
        "motivo": motivo,
    }
    if existing is not None:
        payload["id"] = existing["id"]
        for key in ("duration_ms", "appointment_id", "motivo"):
            if payload[key] is None:
                payload[key] = existing.get(key)
        # Not this function's to touch — they belong to update_call_outcome.
        payload["transcript"] = existing.get("transcript")
        payload["detail"] = existing.get("detail")
    row = _one(remote.upsert("calls", [payload], "call_id"))
    if row is None:
        raise RuntimeError(f"calls upsert returned nothing for {call_id!r}")
    return CallRecord.from_row(row)


def update_call_outcome(
    call_id: str,
    *,
    outcome: str | None = None,
    transcript: str | None = None,
    detail: str | None = None,
    duration_ms: int | None = None,
) -> CallRecord | None:
    """Patch an already-queued outbound call with what actually happened on
    it. ``insert_call`` writes the row the moment a scheduled call is queued
    — before anyone has answered — so its result always needs a second write
    once a Twilio webhook reports it. ``None`` when no row exists yet for
    ``call_id``: a webhook must never mint a ``calls`` row on its own. Every
    parameter left ``None`` keeps the column's current value, so a webhook
    that only knows the transcript cannot blank out an outcome an earlier one
    already set.
    """
    _require_remote()
    existing = _one(remote.select("calls", {"call_id": f"eq.{call_id}", "limit": "1"}))
    if existing is None:
        return None
    values = {
        "outcome": outcome,
        "transcript": transcript,
        "detail": detail,
        "duration_ms": duration_ms,
    }
    values = {key: value for key, value in values.items() if value is not None}
    if not values:
        return CallRecord.from_row(existing)
    row = _one(remote.update("calls", {"call_id": f"eq.{call_id}"}, values))
    return CallRecord.from_row(row) if row else None


def get_call(call_pk: int) -> CallRecord | None:
    row = _one(remote.select("calls", {"id": f"eq.{call_pk}", "limit": "1"}))
    return CallRecord.from_row(row) if row else None


def get_call_by_call_id(call_id: str) -> CallRecord | None:
    """The row for the event log's own id — how a repeated submit on the
    same call finds what it already wrote."""
    row = _one(remote.select("calls", {"call_id": f"eq.{call_id}", "limit": "1"}))
    return CallRecord.from_row(row) if row else None


def link_call_to_appointment(call_pk: int, appointment_id: str) -> None:
    _require_remote()
    remote.update("calls", {"id": f"eq.{call_pk}"}, {"appointment_id": appointment_id})


# ---------------------------------------------------------------------------
# appointments
# ---------------------------------------------------------------------------


def insert_appointment(
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
    rebooked_from_id: str | None = None,
) -> AppointmentRecord:
    """Insert one fresh ``appointments`` row. Write the ``calls`` row first
    (``database/hooks.py`` does): ``booking_call_id`` is where this row says
    which call made this database know about this appointment.
    ``rebooked_from_id`` names the appointment this one replaces, when it
    does — left ``None`` for a booking with no cancellation behind it, the
    common case."""
    _require_remote()
    ts = now_iso()
    payload = {
        "id": id,
        "status": status,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "patient_phone": patient_phone,
        "patient_email": patient_email,
        "provider_id": provider_id,
        "provider_name": provider_name,
        "specialty_id": specialty_id,
        "specialty_name": specialty_name,
        "site_id": site_id,
        "site_name": site_name,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "insurer": insurer,
        "appointment_type_id": appointment_type_id,
        "appointment_type_name": appointment_type_name,
        "reason": reason,
        "booking_call_id": booking_call_id,
        "confirmation_call_id": None,
        "created_at": ts,
        "updated_at": ts,
        "rebooked_from_id": rebooked_from_id,
    }
    row = _one(remote.upsert("appointments", [payload], "id"))
    if row is None:
        raise RuntimeError(f"appointments upsert returned nothing for {id!r}")
    return AppointmentRecord.from_row(row)


def get_appointment(appointment_id: str) -> AppointmentRecord | None:
    row = _one(remote.select("appointments", {"id": f"eq.{appointment_id}", "limit": "1"}))
    return AppointmentRecord.from_row(row) if row else None


def update_appointment(appointment_id: str, **fields: Any) -> AppointmentRecord:
    """Patch any subset of columns (never ``id`` or ``booking_call_id``,
    which never change once written) and bump ``updated_at``."""
    _require_remote()
    values = dict(fields)
    values["updated_at"] = now_iso()
    row = _one(remote.update("appointments", {"id": f"eq.{appointment_id}"}, values))
    if row is None:
        raise KeyError(f"no appointment {appointment_id!r} to update")
    return AppointmentRecord.from_row(row)


def set_confirmation_call(appointment_id: str, call_pk: int) -> None:
    _require_remote()
    remote.update(
        "appointments",
        {"id": f"eq.{appointment_id}"},
        {"confirmation_call_id": call_pk, "updated_at": now_iso()},
    )


def appointments_due_for_confirmation(*, on_date: date) -> list[AppointmentRecord]:
    """Scheduled appointments whose slot falls on ``on_date`` and that have
    not already had a confirmation call placed — the confirmation job's own
    idempotency: running it twice for the same day must not double-dial."""
    rows = remote.select(
        "appointments",
        {
            "status": "eq.scheduled",
            "confirmation_call_id": "is.null",
            "slot_start": f"like.{on_date.isoformat()}*",
            "order": "slot_start",
        },
    )
    return [AppointmentRecord.from_row(row) for row in rows or []]


#: Statuses that still occupy a slot in the diary. ``cancelled`` frees it, and
#: ``no_show``/``completed`` are about a visit that already happened, so the
#: board's forward-looking agenda asks for these two.
OPEN_STATUSES: tuple[str, ...] = ("scheduled", "confirmed")


def list_appointments(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    statuses: tuple[str, ...] = OPEN_STATUSES,
    patient_id: str | None = None,
) -> list[AppointmentRecord]:
    """Appointments in a date window, oldest slot first.

    The window is compared on ``slot_start``'s leading ten characters rather
    than by parsing: ``slot_start`` is stored as tz-aware ISO-8601 with an
    explicit offset, and every row carries Europe/Madrid's, so the leading
    date is already the local calendar day the board draws.
    """
    params: dict[str, str] = {"order": "slot_start"}
    if statuses:
        params["status"] = f"in.({','.join(statuses)})"
    if patient_id:
        params["patient_id"] = f"eq.{patient_id}"
    rows = remote.select("appointments", params) or []
    records = [AppointmentRecord.from_row(row) for row in rows]
    if date_from is not None:
        records = [r for r in records if r.slot_start[:10] >= date_from.isoformat()]
    if date_to is not None:
        records = [r for r in records if r.slot_start[:10] <= date_to.isoformat()]
    return records


def call_id_by_appointment() -> dict[str, str]:
    """``appointments.id`` -> the event log's own ``call_id`` for the call that
    booked it — what a screen needs to link a visit back to its transcript,
    since ``booking_call_id`` is this database's integer key, not the log's."""
    appts = remote.select("appointments", {"select": "id,booking_call_id"})
    calls = remote.select("calls", {"select": "id,call_id"})
    if not appts or not calls:
        return {}
    by_pk = {int(c["id"]): str(c["call_id"]) for c in calls}
    return {
        str(a["id"]): by_pk[int(a["booking_call_id"])]
        for a in appts
        if a.get("booking_call_id") is not None and int(a["booking_call_id"]) in by_pk
    }


# ---------------------------------------------------------------------------
# wall cancellations (the board's Horarios page cancelling by hand)
# ---------------------------------------------------------------------------
#
# This is where the control centre's cancel buttons connect. A wall
# cancellation is not a call, so it writes no ``calls`` row — one
# ``wall_cancellations`` row per slot, and when the appointment also exists
# in ``appointments`` its ``status`` flips to ``cancelled``, the same word a
# phone cancellation writes through ``database/hooks.py``.


def insert_wall_cancellation(
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
    _require_remote()
    row = _one(
        remote.upsert(
            "wall_cancellations",
            [
                {
                    "provider_id": provider_id,
                    "site_id": site_id,
                    "slot_start": slot_start,
                    "appointment_id": appointment_id,
                    "patient_name": patient_name,
                    "provider_name": provider_name,
                    "cancelled_at": now_iso(),
                }
            ],
        )
    )
    if row is None:
        raise RuntimeError("wall_cancellations insert returned nothing")
    return WallCancellationRecord.from_row(row)


def list_wall_cancellations() -> list[WallCancellationRecord]:
    """Every hand-cancelled slot — the set the agenda filters out per request."""
    rows = remote.select("wall_cancellations", {"order": "slot_start"})
    return [WallCancellationRecord.from_row(row) for row in rows or []]


def cancel_appointment_rows(*, provider_id: str, day_from: date, day_to: date) -> list[str]:
    """Batch path: flip every live ``appointments`` row of this doctor whose
    slot falls inside [``day_from``, ``day_to``] to ``cancelled``. Returns the
    ids it touched. Rows this database never knew are unaffected by design —
    their cancellation lives only in ``wall_cancellations``."""
    _require_remote()
    live = remote.select(
        "appointments",
        {
            "provider_id": f"eq.{provider_id}",
            "status": f"in.({','.join(OPEN_STATUSES)})",
            "select": "id,slot_start",
            "order": "slot_start",
        },
    )
    ids = [
        str(row["id"])
        for row in live or []
        if day_from.isoformat() <= str(row["slot_start"])[:10] <= day_to.isoformat()
    ]
    if not ids:
        return []
    remote.update(
        "appointments",
        {"id": f"in.({','.join(ids)})"},
        {"status": "cancelled", "updated_at": now_iso()},
    )
    return ids


def cancel_appointment_row(
    *,
    appointment_id: str | None = None,
    provider_id: str | None = None,
    slot_start: str | None = None,
) -> str | None:
    """Single path: flip one live ``appointments`` row to ``cancelled`` and
    return its id — by ``appointment_id`` when there is one, else by the
    doctor-and-minute the slot key names. ``None`` when nothing live matched."""
    _require_remote()
    live = f"in.({','.join(OPEN_STATUSES)})"
    if appointment_id:
        rows = remote.update(
            "appointments",
            {"id": f"eq.{appointment_id}", "status": live},
            {"status": "cancelled", "updated_at": now_iso()},
        )
        if rows:
            return str(rows[0]["id"])
    if provider_id and slot_start:
        rows = remote.update(
            "appointments",
            {
                "provider_id": f"eq.{provider_id}",
                "slot_start": f"like.{slot_start[:16]}*",
                "status": live,
            },
            {"status": "cancelled", "updated_at": now_iso()},
        )
        if rows:
            return str(rows[0]["id"])
    return None


# ---------------------------------------------------------------------------
# navigating both ways
# ---------------------------------------------------------------------------


def appointment_with_calls(appointment_id: str) -> AppointmentWithCalls | None:
    appt = get_appointment(appointment_id)
    if appt is None:
        return None
    booking_call = get_call(appt.booking_call_id)
    if booking_call is None:
        # Not a foreign key on Postgres (the two tables point at each other),
        # so this is possible in principle — a half-written pair, never a
        # shape any write path in this repo produces.
        log.warning("appointment %s has no booking call %s", appointment_id, appt.booking_call_id)
        return None
    confirmation_call = get_call(appt.confirmation_call_id) if appt.confirmation_call_id else None
    return AppointmentWithCalls(
        appointment=appt, booking_call=booking_call, confirmation_call=confirmation_call
    )


def call_with_appointment(call_pk: int) -> tuple[CallRecord, AppointmentRecord | None] | None:
    call = get_call(call_pk)
    if call is None:
        return None
    appt = get_appointment(call.appointment_id) if call.appointment_id else None
    return call, appt


# ---------------------------------------------------------------------------
# clinic console (settings, pathways, patterns, suggestion rejections)
# ---------------------------------------------------------------------------

CLINIC_SETTINGS_DEFAULTS: dict[str, Any] = {
    "minimum_booking_lead_hours": 24,
    "patient_identification_fields_required": 1,
    "call_time_cap_minutes": 3,
    # E.164, or empty. Empty means the clinic takes no transfers.
    "transfer_number": "",
}


def _settings_from_mapping(row: Any) -> dict[str, Any]:
    return {
        "minimum_booking_lead_hours": int(row["minimum_booking_lead_hours"]),
        "patient_identification_fields_required": int(
            row["patient_identification_fields_required"]
        ),
        "call_time_cap_minutes": int(row["call_time_cap_minutes"]),
        # A database that has not run 0002 yet still answers, with transfers off.
        "transfer_number": str(row.get("transfer_number") or "").strip(),
    }


def get_clinic_settings() -> dict[str, Any]:
    row = _one(remote.select("clinic_settings", {"id": "eq.1", "limit": "1"}))
    if row is None:
        return dict(CLINIC_SETTINGS_DEFAULTS)
    return _settings_from_mapping(row)


def put_clinic_settings(values: dict[str, Any]) -> dict[str, Any]:
    _require_remote()
    lead = max(2, min(96, int(values.get("minimum_booking_lead_hours", 24))))
    fields = max(1, min(4, int(values.get("patient_identification_fields_required", 1))))
    cap = 3
    transfer_number = str(values.get("transfer_number") or "").strip()
    remote.upsert(
        "clinic_settings",
        [
            {
                "id": 1,
                "minimum_booking_lead_hours": lead,
                "patient_identification_fields_required": fields,
                "call_time_cap_minutes": cap,
                "transfer_number": transfer_number,
                "updated_at": now_iso(),
            }
        ],
        "id",
    )
    return get_clinic_settings()


def get_wall_document(kind: str) -> dict[str, Any] | None:
    row = _one(remote.select("wall_documents", {"kind": f"eq.{kind}", "limit": "1"}))
    if row is None:
        return None
    body = row.get("body")
    # jsonb, so PostgREST hands it back already parsed. A string only turns up
    # if a row was written as a JSON-encoded text blob by something older.
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else None
    return None


def put_wall_document(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    _require_remote()
    remote.upsert(
        "wall_documents",
        [{"kind": kind, "body": body, "updated_at": now_iso()}],
        "kind",
    )
    return body


def list_suggestion_rejections(patient_id: str) -> list[str]:
    rows = remote.select(
        "suggestion_rejections",
        {"patient_id": f"eq.{patient_id}", "select": "pattern_id"},
    )
    return sorted({str(row["pattern_id"]) for row in rows or []})


def add_suggestion_rejection(patient_id: str, pattern_id: str) -> None:
    _require_remote()
    remote.upsert(
        "suggestion_rejections",
        [{"patient_id": patient_id, "pattern_id": pattern_id, "rejected_at": now_iso()}],
        "patient_id,pattern_id",
    )
