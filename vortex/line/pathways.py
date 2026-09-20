"""Event-triggered outbound-call pathways.

The system has two registries, and this module is the second one:

- **Call jobs** (``confirmation_calls.CALL_JOBS``) define *what a call says*
  and how the answer is classified: the day-before "¿va a venir?" and the
  cancellation "se ha cancelado su cita, ¿otra fecha?" are jobs.
- **Pathways** (this module) define *what happening fires which job, and at
  whom*. A pathway is the wiring between an event — a visit cancelled on
  the wall, a cancellation said on the phone, a booking just made — and an
  outbound call to the person that event is about.

Every trigger funnels through :func:`fire_pathway`, so the guards live in
exactly one place: the number is normalised to E.164
(``normalise_call_phone``), an empty target skips silently (production
records without a phone have nobody to call), the whole subsystem bows out
when ``VORTEX_CONFIRMATION_CALLS`` is off, and the store's own dedup stops
a double-fire. The caller's phone never decides the pathway — the event
does, via ``PathwayEvent.to`` resolved from the record.

Adding a pathway is a three-line change: register it here, fire it from the
trigger site, and — only if the call must *say* something new — register a
``CallJob`` for the script. See ``docs/pathways.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from vortex.line.confirmation_calls import (
    CANCELLATION_REBOOKING_JOB,
    ConfirmationCall,
    confirmation_store_from_settings,
    normalise_call_phone,
    queue_cancellation_rebooking_call,
    schedule_confirmation_call,
)
from vortex.settings import Settings


@dataclass(frozen=True)
class Pathway:
    """The wiring between an event name and an outbound call.

    ``job`` must be a registered ``CallJob`` id — it carries the script,
    the answer classification and the ack. ``motivo`` selects the queue
    behaviour: ``"call_now"`` places on the very next worker tick (fired
    by something that just happened), ``"programada"`` schedules at the
    job's own lead time (fired by a booking, for the day before).
    """

    name: str
    job: str
    motivo: str
    summary: str


@dataclass(frozen=True)
class PathwayEvent:
    """One happening, resolved to the person it is about.

    ``to`` is the record phone of the patient the event concerns — the
    wall cancel resolves it from the booking, the phone cancel from the
    caller's record — never from the channel the event arrived on.
    ``fallback_to`` is the optional stand-in when the record has no phone
    (``VORTEX_CANCEL_CALL_FALLBACK_TO``; see ``vortex/api/agenda.py``).
    ``already_offered_reschedule`` is the loop guard for events that
    arrive from inside one of these very calls.
    """

    to: str
    appointment_at: datetime
    language: str = ""
    provider_name: str = ""
    location_name: str = ""
    provider_id: str = ""
    location_id: str = ""
    patient_id: str = ""
    appointment_id: str = ""
    fallback_to: str = ""
    already_offered_reschedule: bool = False
    lead: timedelta | None = None


PATHWAYS: dict[str, Pathway] = {}


def register_pathway(pathway: Pathway) -> Pathway:
    """Add a pathway to the system. Guards, queueing and dialing come with it."""
    PATHWAYS[pathway.name] = pathway
    return pathway


def pathway_for(name: str) -> Pathway:
    try:
        return PATHWAYS[name]
    except KeyError:
        raise KeyError(f"unknown outbound-call pathway: {name!r}") from None


def resolve_target_phone(record_phone: str, fallback_to: str = "") -> str:
    """The person the event is *about*, as a dialable E.164 number.

    Trigger sites resolve the record phone; the fallback is only for the
    no-phone-on-record case (demo/testing). Normalisation is idempotent,
    so a number already E.164 passes through unchanged.
    """
    return normalise_call_phone((record_phone or "").strip() or (fallback_to or "").strip())


async def fire_pathway(
    settings: Settings,
    name: str,
    event: PathwayEvent,
    *,
    now: datetime,
) -> ConfirmationCall | None:
    """Fire a registered pathway: queue the outbound call for its event.

    Returns the queued call, or ``None`` when a guard skipped it (empty
    target, subsystem disabled, loop guard, dedup). Never raises for a
    guard — a pathway must not roll back the event that fired it.
    """
    pathway = pathway_for(name)
    if pathway.job == CANCELLATION_REBOOKING_JOB:
        # The cancel pathway carries the loop guard and the product-db
        # mirror of every call_now row; keep them in their one home.
        return await queue_cancellation_rebooking_call(
            settings,
            to=event.to or event.fallback_to,
            appointment_at=event.appointment_at,
            language=event.language,
            provider_name=event.provider_name,
            location_name=event.location_name,
            provider_id=event.provider_id,
            location_id=event.location_id,
            patient_id=event.patient_id,
            appointment_id=event.appointment_id,
            now=now,
            already_offered_reschedule=event.already_offered_reschedule,
        )
    to = resolve_target_phone(event.to, event.fallback_to)
    if not to or not settings.confirmation_calls:
        return None
    store = confirmation_store_from_settings(settings)
    return await schedule_confirmation_call(
        store,
        to=to,
        when=event.appointment_at,
        job=pathway.job,
        language=event.language,
        provider_name=event.provider_name,
        location_name=event.location_name,
        provider_id=event.provider_id,
        location_id=event.location_id,
        patient_id=event.patient_id,
        appointment_id=event.appointment_id,
        now=now,
        lead=event.lead,
        motivo=pathway.motivo,
    )


register_pathway(
    Pathway(
        name="appointment_cancelled",
        job=CANCELLATION_REBOOKING_JOB,
        motivo="call_now",
        summary="A visit was cancelled (wall button or on the phone): call "
        "the patient it belonged to, right away, and offer another date.",
    )
)

register_pathway(
    Pathway(
        name="appointment_booked",
        job="appointment_confirmation",
        motivo="programada",
        summary="A visit was booked on the phone: schedule the day-before "
        "'¿va a venir?' confirmation call to the same patient.",
    )
)
