"""The day-before-the-appointment outbound confirmation job.

Rule: every appointment scheduled for tomorrow gets exactly one outbound
confirmation call, and its result decides the appointment's status —
``confirmed`` if the patient confirms, ``cancelled`` if they cancel on that
same call, unchanged (still ``scheduled``) if nobody answers.

This module decides *which* appointments are due and records what a call
decided; it never itself talks to a phone line. Today the platform this
project dials against only ever calls *us* — there is no outbound-calling
capability anywhere in the codebase or the call contract (grep for
"outbound" and it is Twilio Media Streams frame direction, never a call we
place). ``ConfirmationCaller`` is the seam the line will fill in once that
capability exists; ``SimulatedConfirmationCaller`` is today's stand-in, for
local development and tests. See ``database/README.md``, "What the line
still has to build", for exactly what real implementation would need.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from database import db
from database.models import AppointmentRecord

MADRID = ZoneInfo("Europe/Madrid")

log = logging.getLogger("database.confirmations")

ConfirmationOutcome = Literal["confirmed", "cancel", "no_answer"]

#: What the simulated caller says and, when it isn't a no-answer, what the
#: patient replies — enough to leave a readable transcript behind, not a
#: real conversation.
_SCRIPT_PROMPT = (
    "Llamamos de Clínica Arenal para confirmar su cita del {when}. ¿Podrá acudir?"
)
_SCRIPT_REPLY: dict[ConfirmationOutcome, str] = {
    "confirmed": "Sí, allí estaré.",
    "cancel": "No voy a poder ir, cancele la cita por favor.",
    "no_answer": "",
}


@dataclass(frozen=True)
class ConfirmationResult:
    outcome: ConfirmationOutcome
    #: The event log's own call_id for this outbound call — a confirmation
    #: is a real product event, not a demo, so it is written to
    #: logs/calls.jsonl like any other call and shows up in the console the
    #: same way (see ``SimulatedConfirmationCaller.call``).
    call_id: str
    duration_ms: int | None = None


class ConfirmationCaller(Protocol):
    """What actually places the call. The line implements this for real
    once it can dial out; see the module docstring."""

    async def call(self, appointment: AppointmentRecord) -> ConfirmationResult: ...


class SimulatedConfirmationCaller:
    """Deterministic stand-in used locally and in tests.

    Every appointment confirms unless its id is listed in ``force_outcome``
    — that is how a test (or a local rehearsal) exercises the cancel /
    no_answer branches without a real phone call. Still writes a full
    call.started -> turns -> call.ended -> call.summary trace through the
    ordinary ``CallLog``, tagged with real ``Settings.describe()`` values
    (never ``voice="demo"`` or ``clinic="synthetic-data"``, the markers
    ``business_insights.is_real_call`` excludes) — a confirmation call is
    genuine business activity, not an eval or demo artefact, and Insights
    should count it as such.
    """

    def __init__(
        self,
        *,
        log_path: Path,
        force_outcome: dict[str, ConfirmationOutcome] | None = None,
        settings_describe: dict[str, Any] | None = None,
    ) -> None:
        self._log_path = log_path
        self._force_outcome = force_outcome or {}
        self._settings_describe = settings_describe or {}

    async def call(self, appointment: AppointmentRecord) -> ConfirmationResult:
        from vortex.observability.calllog import CallLog

        outcome = self._force_outcome.get(appointment.id, "confirmed")
        call_id = f"confirm-{appointment.id}-{int(datetime.now(UTC).timestamp() * 1000)}"
        writer = CallLog(call_id, self._log_path)
        writer.event(
            "call.started",
            stream_sid=f"OUT-{call_id}",
            from_number=appointment.patient_phone or "",
            direction="outbound",
            purpose="confirmation",
            **self._settings_describe,
        )
        writer.assistant_turn(_SCRIPT_PROMPT.format(when=appointment.slot_start))
        reply = _SCRIPT_REPLY[outcome]
        if reply:
            writer.user_turn(reply)
        writer.event(
            "call.ended",
            reason="hangup" if reply else "no_answer",
            media_frames_in=0,
            media_frames_out=0,
        )
        writer.summary(reason=outcome)
        duration_ms = None if outcome == "no_answer" else 4000
        return ConfirmationResult(outcome=outcome, call_id=call_id, duration_ms=duration_ms)


async def run_confirmations(
    conn: sqlite3.Connection,
    *,
    caller: ConfirmationCaller,
    today: date | None = None,
) -> list[tuple[AppointmentRecord, ConfirmationResult]]:
    """Call every appointment due tomorrow, once each, and record the result.

    ``today`` defaults to Europe/Madrid's current date. Appointments are
    never booked same-day (CLAUDE.md's own rule), so "tomorrow" always names
    a real future day. Idempotent within a day: an appointment that already
    has a ``confirmation_call_id`` (this function's own previous run, any
    outcome including ``no_answer``) is not dialled again — see
    ``db.appointments_due_for_confirmation``. Retrying a no-answer later the
    same day is a real product's next step, not built here; see
    ``database/README.md``.

    Commits after every appointment, not once at the end: one call failing
    must not roll back the appointments already confirmed earlier in the
    same run. Pass a connection from ``db.connect`` (not the
    ``db.connection`` context manager, which commits only once at the end)
    and close it yourself when done.
    """
    tomorrow = (today or datetime.now(MADRID).date()) + timedelta(days=1)
    due = db.appointments_due_for_confirmation(conn, on_date=tomorrow)
    results: list[tuple[AppointmentRecord, ConfirmationResult]] = []
    for appt in due:
        try:
            result = await caller.call(appt)
        except Exception:
            log.exception("confirmation call failed for appointment %s", appt.id)
            continue
        outbound_call = db.insert_call(
            conn,
            call_id=result.call_id,
            direction="outbound",
            purpose="confirmation",
            from_number=appt.patient_phone,
            started_at=db.now_iso(),
            duration_ms=result.duration_ms,
            outcome=result.outcome,
            appointment_id=appt.id,
        )
        db.set_confirmation_call(conn, appt.id, outbound_call.id)
        if result.outcome == "confirmed":
            db.update_appointment(conn, appt.id, status="confirmed")
        elif result.outcome == "cancel":
            db.update_appointment(conn, appt.id, status="cancelled")
        # no_answer: status stays 'scheduled' — rule 2's "sigue scheduled/pending".
        conn.commit()
        results.append((appt, result))
    return results
