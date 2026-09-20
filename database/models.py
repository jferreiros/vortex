"""Typed rows for the two tables in ``database/schema.py``.

Plain dataclasses, not an ORM — the same shape ``vortex/observability/view.py``
uses for ``CallCard``: one class per row, ``from_row`` to read it back out of
a ``sqlite3.Row``, nothing hidden between the table and the type.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

CallDirection = Literal["inbound", "outbound"]
CallPurpose = Literal["booking", "confirmation", "cancellation", "reschedule", "info", "other"]
CallOutcome = Literal[
    "book",
    "cancel",
    "reschedule",
    "register",
    "no_action",
    "escalate",
    "confirmed",
    "no_answer",
]
AppointmentStatus = Literal["scheduled", "confirmed", "cancelled", "completed", "no_show"]


@dataclass(frozen=True)
class CallRecord:
    id: int
    call_id: str
    direction: CallDirection
    purpose: CallPurpose
    language: str | None
    from_number: str | None
    started_at: str
    duration_ms: int | None
    outcome: CallOutcome | None
    appointment_id: str | None
    #: Why an *outbound* call was placed — confirmacion / recordatorio /
    #: reprogramacion / seguimiento / call_now, mirroring
    #: vortex.line.confirmation_calls.KNOWN_MOTIVOS. NULL for an inbound
    #: call and for any outbound row written before migration 3.
    motivo: str | None = None
    #: What the patient said, best-effort — set by
    #: ``db.update_call_outcome`` once a scheduled outbound call (e.g. a
    #: cancellation's call_now) resolves. NULL until then and for every
    #: inbound call, whose transcript lives in logs/calls.jsonl instead.
    transcript: str | None = None
    #: A status finer than ``outcome``'s closed vocabulary allows — e.g.
    #: ``unclear``/``no_speech``/``no_answer``/``failed`` for a scheduled
    #: outbound call. See migration 5 in schema.py.
    detail: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> CallRecord:
        return cls(
            id=row["id"],
            call_id=row["call_id"],
            direction=row["direction"],
            purpose=row["purpose"],
            language=row["language"],
            from_number=row["from_number"],
            started_at=row["started_at"],
            duration_ms=row["duration_ms"],
            outcome=row["outcome"],
            appointment_id=row["appointment_id"],
            motivo=row["motivo"],
            transcript=row["transcript"],
            detail=row["detail"],
        )


@dataclass(frozen=True)
class AppointmentRecord:
    id: str
    status: AppointmentStatus
    patient_id: str
    patient_name: str | None
    patient_phone: str | None
    patient_email: str | None
    provider_id: str | None
    provider_name: str | None
    specialty_id: str | None
    specialty_name: str | None
    site_id: str | None
    site_name: str | None
    slot_start: str
    slot_end: str
    insurer: str | None
    appointment_type_id: str | None
    appointment_type_name: str | None
    reason: str | None
    booking_call_id: int
    confirmation_call_id: int | None
    created_at: str
    updated_at: str
    #: The appointment this one replaces, when it was booked to fill a slot
    #: a cancellation freed (the cancellation's own call_now callback, taken
    #: up) — set by ``database/hooks.py`` off ``CallSession.handoff``. NULL
    #: for every appointment booked cold, and for any row written before
    #: migration 5.
    rebooked_from_id: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AppointmentRecord:
        return cls(
            id=row["id"],
            status=row["status"],
            patient_id=row["patient_id"],
            patient_name=row["patient_name"],
            patient_phone=row["patient_phone"],
            patient_email=row["patient_email"],
            provider_id=row["provider_id"],
            provider_name=row["provider_name"],
            specialty_id=row["specialty_id"],
            specialty_name=row["specialty_name"],
            site_id=row["site_id"],
            site_name=row["site_name"],
            slot_start=row["slot_start"],
            slot_end=row["slot_end"],
            insurer=row["insurer"],
            appointment_type_id=row["appointment_type_id"],
            appointment_type_name=row["appointment_type_name"],
            reason=row["reason"],
            booking_call_id=row["booking_call_id"],
            confirmation_call_id=row["confirmation_call_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            rebooked_from_id=row["rebooked_from_id"],
        )


@dataclass(frozen=True)
class WallCancellationRecord:
    """One slot the control centre (the board's Horarios page) freed by hand.

    Not a call: the join key is the diary slot (``provider_id``, ``site_id``,
    ``slot_start``), never a ``calls`` row — see schema.py's migration-2
    comment for why.
    """

    id: int
    provider_id: str
    site_id: str
    slot_start: str
    appointment_id: str | None
    patient_name: str | None
    provider_name: str | None
    cancelled_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> WallCancellationRecord:
        return cls(
            id=row["id"],
            provider_id=row["provider_id"],
            site_id=row["site_id"],
            slot_start=row["slot_start"],
            appointment_id=row["appointment_id"],
            patient_name=row["patient_name"],
            provider_name=row["provider_name"],
            cancelled_at=row["cancelled_at"],
        )


@dataclass(frozen=True)
class AppointmentWithCalls:
    """An appointment plus its two named calls, resolved — the "navigable
    both ways" shape the FK pair exists for: from the appointment you reach
    the call that booked it and the one that confirmed it (if any) without a
    second round trip through ``id``."""

    appointment: AppointmentRecord
    booking_call: CallRecord
    confirmation_call: CallRecord | None
