"""The write hook: turns an accepted book/cancel/reschedule submission into
database rows.

One entry point, ``persist_submission``, called from
``vortex/line/submit.py`` right where that module already reacts to "this
action really happened" (the same ``result.status in {"accepted",
"duplicate"}`` check that invalidates the availability cache). The source is
the submit's own ``Action`` — never an intermediate tool call — so what
lands here is exactly what the platform accepted, not a plan that was later
revised.

Never raises into the call: a database problem must not end or distort a
call any more than a broken ``voiceconfig.db`` read does
(``vortex/line/voice_config.py``'s own rule). Every public function here
catches broadly and logs; the call keeps going either way.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from database import db
from database.db import DEFAULT_DB_PATH
from vortex.contract import (
    Action,
    BookAction,
    CancelAction,
    RescheduleAction,
    ToolContext,
    recall_patient,
)
from vortex.conversation.language import detect_language

log = logging.getLogger("database.hooks")


def _identified_patient(ctx: ToolContext) -> Any:
    # Late import: vortex.line.session imports vortex.line.submit (which
    # imports this module), so importing it at module load time would be a
    # cycle. session.py already does the same late import for the same
    # reason (see with_verdict_reason in vortex/line/submit.py).
    from vortex.line.session import CallMemory

    return CallMemory.of(ctx).identified_patient


def _call_language(ctx: ToolContext) -> str | None:
    """Best-effort ISO-639-1 code for the language this call has been in so
    far — ``detect_language`` over every caller turn recorded up to now
    (``CallLog.caller_words``), the same signal ``triage`` and
    ``business_insights`` already read the caller's own words through.
    ``None`` when the caller has not said anything yet (should not happen
    by submit time, but a database write is never worth failing over)."""
    words = ctx.log.caller_words()
    return detect_language(words) if words else None


def _reason(ctx: ToolContext, limit: int = 240) -> str | None:
    """Best-effort "motivo": there is no structured chief-complaint field in
    the submit contract, so this is the caller's own recent words, capped.
    Never authoritative — a free-text hint, not a diagnosis."""
    words = ctx.log.caller_words()
    return words[:limit] if words else None


async def _provider_site_type(
    ctx: ToolContext,
    provider_id: str | None,
    location_id: str | None,
    appointment_type_id: str | None,
) -> tuple[Any, Any, Any]:
    """Names to go with the ids the action carries — one catalogue call,
    typically already warm in the clinic client's own cache by submit time
    since the same lookup happened earlier in the call."""
    catalogue = await ctx.clinic.catalogue()
    provider = next(
        (p for p in catalogue.providers if p.provider_id == provider_id), None
    )
    site = next((s for s in catalogue.locations if s.location_id == location_id), None)
    appt_type = next(
        (t for t in catalogue.appointment_types if t.appointment_type_id == appointment_type_id),
        None,
    )
    return provider, site, appt_type


async def _backfill_appointment(
    ctx: ToolContext, conn: Any, appointment_id: str, call_pk: int
) -> Any:
    """An appointment this database has never seen before: it predates this
    system, or a cancel/reschedule was the first call to ever touch it here.

    The clinic is read-only and never learns about a booking we only
    reported to the scoring platform (see ``.claude/skills/submit-action``),
    so **every** cancel/reschedule this line ever submits necessarily
    targets an appointment that already existed before any call of ours —
    there is no scenario in this challenge where a caller books through us
    and later calls back to cancel that same booking. Recovering the slot,
    provider and patient facts from the read-only clinic (which does know
    its own seed data) is therefore the normal path here, not a rare
    fallback — see ``database/README.md``, "Why booking_call_id is never
    NULL", for the full reasoning and its one honest gap: without a real
    booking call to point at, ``booking_call_id`` is set to *this*
    (cancelling/rescheduling) call, which is discovery, not booking.
    """
    patient = _identified_patient(ctx)
    if patient is None:
        log.warning(
            "cancel/reschedule of unseen appointment %s with no identified "
            "patient on call %s; not backfilling a row",
            appointment_id,
            ctx.call_id,
        )
        return None
    try:
        appointments = await ctx.clinic.appointments(patient.patient_id, when="all")
    except Exception:
        log.exception(
            "clinic lookup failed while backfilling appointment %s (call %s)",
            appointment_id,
            ctx.call_id,
        )
        return None
    match = next((a for a in appointments if a.appointment_id == appointment_id), None)
    if match is None:
        log.warning(
            "appointment %s not found among patient %s's appointments; not backfilling",
            appointment_id,
            patient.patient_id,
        )
        return None
    provider, site, appt_type = await _provider_site_type(
        ctx, match.provider_id, match.location_id, match.appointment_type_id
    )
    slot_end = match.start + timedelta(minutes=match.duration_minutes)
    return db.insert_appointment(
        conn,
        id=appointment_id,
        booking_call_id=call_pk,
        status="scheduled",
        patient_id=patient.patient_id,
        patient_name=patient.full_name,
        patient_phone=patient.phone,
        patient_email=patient.email,
        provider_id=match.provider_id,
        provider_name=provider.name if provider else None,
        specialty_id=provider.specialty_id if provider else None,
        specialty_name=provider.specialty_name if provider else None,
        site_id=match.location_id,
        site_name=site.name if site else None,
        slot_start=match.start.isoformat(),
        slot_end=slot_end.isoformat(),
        appointment_type_id=match.appointment_type_id,
        appointment_type_name=appt_type.name if appt_type else None,
    )


async def _record_booking(ctx: ToolContext, action: BookAction, db_path: Path | str | None) -> None:
    with db.connection(db_path) as conn:
        existing = db.get_call_by_call_id(conn, ctx.call_id)
        if existing is not None and existing.appointment_id is not None:
            return  # a retried identical submit; nothing new to write

        patient = recall_patient(ctx, action.patient_id)
        provider, site, appt_type = await _provider_site_type(
            ctx, action.provider_id, action.location_id, action.appointment_type_id
        )
        duration = appt_type.duration_minutes if appt_type else 15
        slot_end = action.slot + timedelta(minutes=duration)

        call = db.insert_call(
            conn,
            call_id=ctx.call_id,
            direction="inbound",
            purpose="booking",
            language=_call_language(ctx),
            from_number=ctx.from_number,
            started_at=ctx.now.isoformat(),
            outcome="book",
        )
        # A locally-minted id: the clinic is read-only, so a book
        # submission never gets one back (see _backfill_appointment's
        # docstring for the other side of this same fact).
        appointment_id = f"LCL-{uuid4().hex[:16]}"
        db.insert_appointment(
            conn,
            id=appointment_id,
            booking_call_id=call.id,
            patient_id=action.patient_id,
            patient_name=patient.full_name if patient else None,
            patient_phone=patient.phone if patient else None,
            patient_email=patient.email if patient else None,
            provider_id=action.provider_id,
            provider_name=provider.name if provider else None,
            specialty_id=provider.specialty_id if provider else None,
            specialty_name=provider.specialty_name if provider else None,
            site_id=action.location_id,
            site_name=site.name if site else None,
            slot_start=action.slot.isoformat(),
            slot_end=slot_end.isoformat(),
            insurer=action.policy_id,
            appointment_type_id=action.appointment_type_id,
            appointment_type_name=appt_type.name if appt_type else None,
            reason=_reason(ctx),
        )
        db.link_call_to_appointment(conn, call.id, appointment_id)


async def _record_cancellation(
    ctx: ToolContext, action: CancelAction, db_path: Path | str | None
) -> None:
    with db.connection(db_path) as conn:
        # appointment_id starts NULL: the row it should point at may not
        # exist yet (the "unseen appointment" backfill case below), and the
        # column is FK-enforced, so linking happens only once the
        # appointment is known to exist.
        call = db.insert_call(
            conn,
            call_id=ctx.call_id,
            direction="inbound",
            purpose="cancellation",
            language=_call_language(ctx),
            from_number=ctx.from_number,
            started_at=ctx.now.isoformat(),
            outcome="cancel",
        )
        appt = db.get_appointment(conn, action.appointment_id)
        if appt is None:
            appt = await _backfill_appointment(ctx, conn, action.appointment_id, call.id)
            if appt is None:
                return
        db.link_call_to_appointment(conn, call.id, action.appointment_id)
        db.update_appointment(conn, action.appointment_id, status="cancelled")


async def _record_reschedule(
    ctx: ToolContext, action: RescheduleAction, db_path: Path | str | None
) -> None:
    with db.connection(db_path) as conn:
        # Same NULL-then-link order as _record_cancellation — see its comment.
        call = db.insert_call(
            conn,
            call_id=ctx.call_id,
            direction="inbound",
            purpose="reschedule",
            language=_call_language(ctx),
            from_number=ctx.from_number,
            started_at=ctx.now.isoformat(),
            outcome="reschedule",
        )
        appt = db.get_appointment(conn, action.appointment_id)
        if appt is None:
            appt = await _backfill_appointment(ctx, conn, action.appointment_id, call.id)
            if appt is None:
                return
        db.link_call_to_appointment(conn, call.id, action.appointment_id)
        provider, site, appt_type = await _provider_site_type(
            ctx, action.provider_id, action.location_id, appt.appointment_type_id
        )
        duration = appt_type.duration_minutes if appt_type else 15
        slot_end = action.slot + timedelta(minutes=duration)
        db.update_appointment(
            conn,
            action.appointment_id,
            # A new date needs its own confirmation call — an earlier
            # "confirmed" for the old slot says nothing about this one.
            status="scheduled",
            provider_id=action.provider_id,
            provider_name=provider.name if provider else appt.provider_name,
            specialty_id=provider.specialty_id if provider else appt.specialty_id,
            specialty_name=provider.specialty_name if provider else appt.specialty_name,
            site_id=action.location_id,
            site_name=site.name if site else appt.site_name,
            slot_start=action.slot.isoformat(),
            slot_end=slot_end.isoformat(),
            insurer=action.policy_id,
        )


async def persist_submission(
    ctx: ToolContext, action: Action, *, db_path: Path | str | None = DEFAULT_DB_PATH
) -> None:
    """Persist a book/cancel/reschedule submission. A no-op for register,
    no-action and escalate: this database models appointments, and none of
    those three touch one (see ``database/README.md``, "What this database
    does not model").

    Never raises: logs and returns on any failure, same rule as every other
    piece of call telemetry in this codebase.
    """
    try:
        if isinstance(action, BookAction):
            await _record_booking(ctx, action, db_path)
        elif isinstance(action, CancelAction):
            await _record_cancellation(ctx, action, db_path)
        elif isinstance(action, RescheduleAction):
            await _record_reschedule(ctx, action, db_path)
    except Exception:
        log.exception(
            "could not persist %s submission for call %s", action.kind, ctx.call_id
        )
