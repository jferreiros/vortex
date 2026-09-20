"""``/api/wall`` diary routes: the dropdowns, the month grid, and the cancels.

The Horarios page's "Cancelar" buttons land here. The data layer is
``database/db.py`` (Postgres): one ``wall_cancellations`` row per freed slot,
plus a status flip on ``appointments`` when the appointment exists there —
the same ``cancelled`` a phone cancellation writes through
``database/hooks.py``. Reads then drop those slots via ``cal.drop_cancelled``,
so a cancelled visit simply shows as a free slot, the same thing a CANCEL
replayed from the call log does. Every cancelled visit with a patient on it
also lands in the rebooking queue as a pending ``reschedule`` — the outbound
dialer calls the patient back for a new slot. Nothing is submitted anywhere:
the clinic's own diary is the system of record here.

A write with Supabase unconfigured raises ``RuntimeError`` in ``db``; that
becomes a 503 rather than a 500, because the slot is not cancelled and the
page must be able to say so.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from vortex.api import _shared
from vortex.observability import calendar as cal
from vortex.settings import get_settings

log = logging.getLogger("vortex.api")
router = APIRouter()

MADRID = ZoneInfo("Europe/Madrid")

STORE_DOWN = {"ok": False, "error": "store_unavailable"}


@router.get("/agenda-options")
def wall_agenda_options_api() -> JSONResponse:
    """Doctors, sites, specialties and appointment types for the diary dropdowns."""
    return JSONResponse(cal.agenda_options(_shared.agenda_catalogue()))


@router.get("/doctor-suggest")
def wall_doctor_suggest_api(q: str = "") -> JSONResponse:
    """Name typeahead. Empty query returns an empty list, never the full roster."""
    calendars = cal.build_calendars(_shared.agenda_catalogue(), {})
    return JSONResponse(cal.suggest_doctors(calendars, q))


@router.get("/doctor-agenda")
def wall_doctor_agenda_api(
    name: str = "",
    specialty: str = "",
    week: str | None = None,
    month: str | None = None,
    today: str | None = None,
) -> JSONResponse:
    """Month grid of booked visits. Doctor is optional; specialty is enough."""
    catalogue = _shared.agenda_catalogue()
    if today:
        try:
            today_date = date.fromisoformat(today)
        except ValueError:
            today_date = datetime.now(MADRID).date()
    else:
        today_date = datetime.now(MADRID).date()
    week_date = None
    if week:
        try:
            week_date = date.fromisoformat(week)
        except ValueError:
            week_date = None
    month_date = None
    if month:
        raw = month.strip()
        if len(raw) == 7:
            raw = f"{raw}-01"
        try:
            month_date = date.fromisoformat(raw)
        except ValueError:
            month_date = None
    calendars = cal.build_calendars(catalogue, _shared.agenda_bookings_live())
    payload = cal.clinic_agenda(
        calendars,
        _shared.agenda_patients(),
        name=name,
        specialty_id=specialty,
        today=today_date,
        week=week_date,
        month=month_date,
        location_names={loc.location_id: loc.name for loc in catalogue.locations},
        type_names={item.appointment_type_id: item.name for item in catalogue.appointment_types},
        type_durations={
            item.appointment_type_id: item.duration_minutes for item in catalogue.appointment_types
        },
        plan_names={plan.insurer_id: plan.name for plan in catalogue.insurance_plans},
    )
    return JSONResponse(payload)


# ---- Cancellations ---------------------------------------------------------


def _enqueue_rebookings(bookings: list[cal.Booking]) -> int:
    """One pending ``rebooking_requests`` row per cancelled visit — the queue
    ``vortex/diary/rebooking.py``'s watcher re-checks and the line's outbound
    dialer drains once it can place calls. A failed queue must not roll back a
    cancel that already committed, so this logs and degrades to 0 instead of
    propagating."""
    from vortex.diary import rebooking

    today = datetime.now(MADRID).date()
    try:
        store = rebooking.RebookingStore()
    except Exception:
        log.exception("rebooking queue unavailable; cancelled slots stay cancelled")
        return 0
    queued = 0
    for booking in bookings:
        request = rebooking.wall_cancel_request(
            provider_id=booking.provider_id,
            location_id=booking.location_id,
            slot_start=booking.start,
            patient_id=booking.patient_id,
            appointment_id=booking.appointment_id or None,
            today=today,
        )
        if request is None:
            continue  # no patient on the visit — nobody to call back
        try:
            store.add(request)
            queued += 1
        except Exception:
            log.exception("rebooking enqueue failed for slot %s", booking.start.isoformat())
    return queued


async def _enqueue_call_now_rebooking_calls(bookings: list[cal.Booking]) -> int:
    """Queue an immediate call_now per cancelled visit with a phone on file
    — an actual outbound call offering another date, not the silent
    availability watch ``_enqueue_rebookings`` runs. See
    ``vortex.line.confirmation_calls.queue_cancellation_rebooking_call``,
    which also mirrors the row into the product database. A failed queue
    must not roll back a cancel that already committed, so this logs and
    degrades to 0 instead of propagating."""
    from vortex.line.pathways import PathwayEvent, fire_pathway, resolve_target_phone

    catalogue = _shared.agenda_catalogue()
    patients = _shared.agenda_patients()
    settings = get_settings()
    now = datetime.now(MADRID)
    queued = 0
    for booking in bookings:
        person = patients.get(booking.patient_id)
        # The call goes to the patient the cancelled visit belonged to.
        # VORTEX_CANCEL_CALL_FALLBACK_TO is the demo/testing stand-in when
        # the record has no phone; whoever sets it chooses (and must have
        # the agreement of) the person who receives the call.
        phone = resolve_target_phone(
            (person.phone if person else "") or "",
            settings.cancel_call_fallback_to,
        )
        if not phone:
            continue
        provider = next(
            (p for p in catalogue.providers if p.provider_id == booking.provider_id), None
        )
        location = next(
            (s for s in catalogue.locations if s.location_id == booking.location_id), None
        )
        try:
            call = await fire_pathway(
                settings,
                "appointment_cancelled",
                PathwayEvent(
                    to=phone,
                    appointment_at=booking.start,
                    provider_name=provider.name if provider else "",
                    location_name=location.name if location else "",
                    provider_id=booking.provider_id,
                    location_id=booking.location_id,
                    patient_id=booking.patient_id,
                    appointment_id=booking.appointment_id or "",
                ),
                now=now,
            )
        except Exception:
            log.exception("call_now rebooking queue failed for slot %s", booking.start.isoformat())
            continue
        if call is not None:
            queued += 1
    return queued


def _parse_day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        return None


def _cancel_range_args(payload: Any) -> tuple[str, date | None, date | None, str | None]:
    """Shared validation for the two range routes. ``from`` > ``to`` is a
    slips-of-the-mouse case, not an error — the range swaps ends."""
    if not isinstance(payload, dict):
        return "", None, None, "bad_request"
    provider_id = str(payload.get("provider_id") or "").strip()
    day_from = _parse_day(payload.get("from"))
    day_to = _parse_day(payload.get("to"))
    if not provider_id:
        return provider_id, day_from, day_to, "missing_doctor"
    if day_from is None or day_to is None:
        return provider_id, day_from, day_to, "missing_dates"
    if day_from > day_to:
        day_from, day_to = day_to, day_from
    return provider_id, day_from, day_to, None


def _cancel_targets(
    provider_id: str, day_from: date, day_to: date
) -> tuple[str, list[cal.Booking]]:
    """One doctor's still-booked slots inside the range — the exact set a
    range cancel frees, so preview and confirm can never disagree on what
    "all appointments in the range" means."""
    catalogue = _shared.agenda_catalogue()
    provider = next((p for p in catalogue.providers if p.provider_id == provider_id), None)
    if provider is None:
        return "", []
    hits = [
        booking
        for booking in _shared.agenda_bookings_live().values()
        if booking.provider_id == provider_id
        and day_from <= booking.start.astimezone(MADRID).date() <= day_to
    ]
    return provider.name, sorted(hits, key=lambda booking: booking.start)


def _cancel_sample(bookings: list[cal.Booking], limit: int = 8) -> list[dict[str, str]]:
    """The first few affected visits, for the modal's "this is what goes" list."""
    patients = _shared.agenda_patients()
    sample = []
    for booking in bookings[:limit]:
        person = patients.get(booking.patient_id)
        start = booking.start.astimezone(MADRID)
        sample.append(
            {
                "date": start.date().isoformat(),
                "time": start.strftime("%H:%M"),
                "full_name": (person.full_name if person else "") or "Cita",
            }
        )
    return sample


@router.post("/agenda/cancel-preview")
async def wall_cancel_preview_api(request: Request) -> JSONResponse:
    """The count (and a sample) a range cancel would free — the number the
    modal shows before its explicit confirm. Writes nothing."""
    provider_id, day_from, day_to, err = _cancel_range_args(await request.json())
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    doctor, hits = _cancel_targets(provider_id, day_from, day_to)
    if not doctor:
        return JSONResponse({"ok": False, "error": "unknown_doctor"}, status_code=404)
    return JSONResponse(
        {
            "ok": True,
            "doctor": doctor,
            "count": len(hits),
            "sample": _cancel_sample(hits),
        }
    )


@router.post("/agenda/cancel")
async def wall_cancel_range_api(request: Request) -> JSONResponse:
    """Batch cancel: every booked slot of one doctor inside [from, to]."""
    provider_id, day_from, day_to, err = _cancel_range_args(await request.json())
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    doctor, hits = _cancel_targets(provider_id, day_from, day_to)
    if not doctor:
        return JSONResponse({"ok": False, "error": "unknown_doctor"}, status_code=404)
    from database import db

    patients = _shared.agenda_patients()
    try:
        for booking in hits:
            person = patients.get(booking.patient_id)
            db.insert_wall_cancellation(
                provider_id=booking.provider_id,
                site_id=booking.location_id,
                slot_start=booking.start.astimezone(MADRID).isoformat(),
                appointment_id=booking.appointment_id or None,
                patient_name=person.full_name if person else None,
                provider_name=doctor,
            )
        touched = db.cancel_appointment_rows(
            provider_id=provider_id, day_from=day_from, day_to=day_to
        )
    except RuntimeError:
        log.warning("wall range cancel could not write; nothing was cancelled")
        return JSONResponse(STORE_DOWN, status_code=503)
    queued = _enqueue_rebookings(hits)
    call_now_queued = await _enqueue_call_now_rebooking_calls(hits)
    return JSONResponse(
        {
            "ok": True,
            "doctor": doctor,
            "cancelled": len(hits),
            "appointments_updated": len(touched),
            "rebookings_queued": queued,
            "call_now_queued": call_now_queued,
        }
    )


@router.post("/appointments/cancel")
async def wall_cancel_visit_api(request: Request) -> JSONResponse:
    """Single cancel from a visit's detail view. The body names the slot the
    way the diary keys it — provider + site + minute — and the server takes
    every other fact (patient, appointment id) from the booking itself."""
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "bad_request"}, status_code=400)
    provider_id = str(payload.get("provider_id") or "").strip()
    location_id = str(payload.get("location_id") or "").strip()
    key = cal.cancel_key(provider_id, location_id, payload.get("slot_start"))
    if key is None:
        return JSONResponse({"ok": False, "error": "bad_slot"}, status_code=400)
    booking = _shared.agenda_bookings_live().get(key)
    if booking is None:
        # Free already (or never booked, or cancelled earlier) — a wall cancel
        # must never mint a row for a slot nothing was on.
        return JSONResponse({"ok": False, "error": "not_booked"}, status_code=409)
    catalogue = _shared.agenda_catalogue()
    provider = next((p for p in catalogue.providers if p.provider_id == provider_id), None)
    person = _shared.agenda_patients().get(booking.patient_id)
    from database import db

    try:
        db.insert_wall_cancellation(
            provider_id=provider_id,
            site_id=location_id,
            slot_start=booking.start.astimezone(MADRID).isoformat(),
            appointment_id=booking.appointment_id or None,
            patient_name=person.full_name if person else None,
            provider_name=provider.name if provider else None,
        )
        touched = db.cancel_appointment_row(
            appointment_id=booking.appointment_id or None,
            provider_id=provider_id,
            slot_start=booking.start.astimezone(MADRID).isoformat(),
        )
    except RuntimeError:
        log.warning("wall cancel could not write; the slot stays booked")
        return JSONResponse(STORE_DOWN, status_code=503)
    queued = _enqueue_rebookings([booking])
    call_now_queued = await _enqueue_call_now_rebooking_calls([booking])
    return JSONResponse(
        {
            "ok": True,
            "appointment_updated": touched,
            "rebookings_queued": queued,
            "call_now_queued": call_now_queued,
        }
    )
