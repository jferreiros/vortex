"""Per-doctor calendars for the board.

Builds, for each provider, a day x time grid from the clinic catalogue
(opening hours, closure days, the bookable window) and fills the slots the call
log says were booked, moved or cancelled.

The Clinic View's filled slots come from ``public.appointments``, which the
line writes as each submission lands: real visits, on the real providers and
sites. A table with no appointments falls back to the synthetic-data pack, so
a fresh clone still draws a populated diary.

The standalone ``/calendar`` page reads the pack's own logs
(``synthetic-data/logs/*.jsonl``); set ``VORTEX_CALENDAR_LOG`` to a single
CallLog-shaped fixture to fill that grid from it instead.

The builders (``bookings_from_events``, ``bookings_from_rows``,
``build_calendars``, ``clinic_agenda``) are pure: they take data and return
data, so the view and the tests share one code path. The IO helpers
(``appointment_index``, ``load_source_events``, ``load_database_agenda``,
``load_agenda_bookings``) sit at the bottom.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from vortex.contract import (
    MADRID,
    Appointment,
    AppointmentTypeRecord,
    Catalogue,
    PatientRecord,
    ProviderRecord,
)
from vortex.settings import REPO_ROOT

#: Hugging Face Inference summarization. Optional; the view shows the raw note
#: when ``HF_TOKEN`` is missing or the call fails.
HF_SUMMARIZE_URL = "https://router.huggingface.co/hf-inference/models/facebook/bart-large-cnn"
#: Notes shorter than this are already one line; skip the API.
SHORT_NOTE_WORDS = 40

CellStatus = Literal["free", "booked"]

#: The three submitted verbs that move a slot in or out of a diary. NO_ACTION,
#: REGISTER and ESCALATE never touch a calendar, so they are ignored here.
_DIARY_ACTIONS = frozenset({"BOOK", "CANCEL", "RESCHEDULE"})

#: A booking key is per (provider, site, minute). The instant is normalised to
#: Europe/Madrid so a slot written with any offset lands on the same grid cell.
BookingKey = tuple[str, str, datetime]


@dataclass(frozen=True)
class Booking:
    """One slot the log says is taken, keyed to a doctor, a site and a minute."""

    provider_id: str
    location_id: str
    start: datetime
    patient_id: str = ""
    appointment_type_id: str = ""
    appointment_id: str = ""
    call_id: str = ""


@dataclass
class CalendarCell:
    """One 15-minute step in a doctor's day, free or booked."""

    start: datetime
    status: CellStatus = "free"
    patient_id: str = ""
    appointment_type_id: str = ""
    location_id: str = ""
    call_id: str = ""
    #: Which diary this cell sits on and which clinic appointment fills it —
    #: the pair a wall cancellation keys on (BookingKey's provider leg is the
    #: calendar's own; keeping it here lets a visit row carry it downstream).
    provider_id: str = ""
    appointment_id: str = ""


@dataclass(frozen=True)
class PatientBrief:
    """The roster fields a doctor needs for one visit, keyed by ``patient_id``."""

    patient_id: str
    full_name: str
    phone: str = ""
    insurer: str = ""
    note: str = ""
    has_visited_before: bool = False
    sex: str = ""
    date_of_birth: str = ""


@dataclass(frozen=True)
class VisitBrief:
    """One booked cell joined to the roster, ready for the briefing card."""

    start: datetime
    patient_id: str
    full_name: str
    phone: str = ""
    insurer: str = ""
    note: str = ""
    has_visited_before: bool = False
    appointment_type: str = ""
    appointment_type_id: str = ""
    location_id: str = ""
    location_name: str = ""
    sex: str = ""
    age: str = ""
    provider_id: str = ""
    appointment_id: str = ""


@dataclass
class DoctorDay:
    """One open day for one doctor, its steps sorted earliest first."""

    day: date
    cells: list[CalendarCell] = field(default_factory=list)

    @property
    def booked(self) -> int:
        return sum(1 for cell in self.cells if cell.status == "booked")


@dataclass
class DoctorCalendar:
    """One doctor's diary across the visible window."""

    provider_id: str
    name: str
    specialty: str = ""
    specialty_id: str = ""
    location_ids: list[str] = field(default_factory=list)
    days: list[DoctorDay] = field(default_factory=list)

    @property
    def capacity(self) -> int:
        return sum(len(day.cells) for day in self.days)

    @property
    def booked(self) -> int:
        return sum(day.booked for day in self.days)

    @property
    def times(self) -> list[time]:
        """Every distinct start time across the open days, earliest first."""
        seen = {cell.start.timetz().replace(tzinfo=None) for day in self.days for cell in day.cells}
        return sorted(seen)


# ---------------------------------------------------------------------------
# Pure builders
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    """An ISO timestamp -> a Madrid-aware datetime, or ``None`` if unparseable."""
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=MADRID)
    return stamp.astimezone(MADRID)


def _key(provider_id: str, location_id: str, start: datetime) -> BookingKey:
    return (provider_id, location_id, start.astimezone(MADRID).replace(second=0, microsecond=0))


def _apply_book(
    bookings: dict[BookingKey, Booking],
    payload: dict[str, Any],
    call_id: str,
    *,
    appointment_id: str = "",
) -> Booking | None:
    """Place the slot a BOOK (or the new leg of a RESCHEDULE) names."""
    provider_id = str(payload.get("provider_id") or "")
    location_id = str(payload.get("location_id") or "")
    start = _parse_dt(payload.get("slot"))
    if not provider_id or start is None:
        return None
    start = start.replace(second=0, microsecond=0)
    booking = Booking(
        provider_id=provider_id,
        location_id=location_id,
        start=start,
        patient_id=str(payload.get("patient_id") or ""),
        appointment_type_id=str(payload.get("appointment_type_id") or ""),
        appointment_id=appointment_id,
        call_id=call_id,
    )
    bookings[_key(provider_id, location_id, start)] = booking
    return booking


def bookings_from_appointments(items: list[Appointment]) -> dict[BookingKey, Booking]:
    """Taken slots from ``GET /patients/{id}/appointments``, keyed like the log."""
    bookings: dict[BookingKey, Booking] = {}
    for item in items:
        if not item.provider_id or not item.patient_id:
            continue
        start = item.start.astimezone(MADRID).replace(second=0, microsecond=0)
        bookings[_key(item.provider_id, item.location_id, start)] = Booking(
            provider_id=item.provider_id,
            location_id=item.location_id,
            start=start,
            patient_id=item.patient_id,
            appointment_type_id=item.appointment_type_id,
            appointment_id=item.appointment_id,
        )
    return bookings


def assign_provider(catalogue: Catalogue, booking: Booking) -> Booking:
    """Give a diary row a real ``provider_id`` when the pack left it blank.

    ``appointments.json`` often knows the site and type but not the doctor.
    The board still has to hang that visit on someone's grid, so we pick the
    first catalogue provider at that site (and of that type's specialty, when
    the type is not universal). A row that already names a doctor is unchanged.
    """
    if booking.provider_id:
        return booking
    provider_id = _provider_for_slot(catalogue, booking.location_id, booking.appointment_type_id)
    if not provider_id:
        return booking
    return replace(booking, provider_id=provider_id)


def _provider_for_slot(catalogue: Catalogue, location_id: str, appointment_type_id: str) -> str:
    type_specialty = next(
        (
            row.specialty_id
            for row in catalogue.appointment_types
            if row.appointment_type_id == appointment_type_id
        ),
        None,
    )

    def at_site(provider: Any) -> bool:
        return not location_id or location_id in provider.location_ids

    ranked = [
        provider
        for provider in catalogue.providers
        if at_site(provider) and (not type_specialty or provider.specialty_id == type_specialty)
    ]
    if not ranked:
        ranked = [provider for provider in catalogue.providers if at_site(provider)]
    if not ranked:
        ranked = list(catalogue.providers)
    return ranked[0].provider_id if ranked else ""


def bookings_from_rows(
    rows: list[Any],
    call_ids: dict[str, str] | None = None,
    *,
    catalogue: Catalogue | None = None,
) -> dict[BookingKey, Booking]:
    """Taken slots from ``database/`` appointment rows, keyed like the log.

    Pure: ``rows`` are ``database.models.AppointmentRecord``-shaped and the
    caller does the reading. No event replay is needed — the database is the
    diary already materialised, so a cancelled appointment is simply absent
    from an open-status read and a rescheduled one already names its new slot.
    """
    call_ids = call_ids or {}
    bookings: dict[BookingKey, Booking] = {}
    for row in rows:
        start = _parse_dt(row.slot_start)
        if start is None:
            continue
        start = start.astimezone(MADRID).replace(second=0, microsecond=0)
        booking = Booking(
            provider_id=str(row.provider_id or ""),
            location_id=str(row.site_id or ""),
            start=start,
            patient_id=str(row.patient_id or ""),
            appointment_type_id=str(row.appointment_type_id or ""),
            appointment_id=str(row.id or ""),
            call_id=call_ids.get(str(row.id or ""), ""),
        )
        if catalogue is not None:
            booking = assign_provider(catalogue, booking)
        if not booking.provider_id:
            continue
        bookings[_key(booking.provider_id, booking.location_id, booking.start)] = booking
    return bookings


def patient_index_from_rows(rows: list[Any]) -> dict[str, PatientBrief]:
    """``patient_id`` -> the roster fields the appointment rows carry.

    The database knows a patient only through the calls that booked them, so a
    row whose call never ran ``find_patient`` has an id and no name. Those are
    skipped rather than shown as a blank card: the directory is a better source
    for anyone it does know, and this index only fills the gaps it can.
    """
    index: dict[str, PatientBrief] = {}
    for row in rows:
        patient_id = str(row.patient_id or "")
        if not patient_id or not row.patient_name:
            continue
        index.setdefault(
            patient_id,
            PatientBrief(
                patient_id=patient_id,
                full_name=str(row.patient_name),
                phone=str(row.patient_phone or ""),
                insurer=str(row.insurer or ""),
            ),
        )
    return index


def providers_from_events(events: list[dict[str, Any]]) -> list[ProviderRecord]:
    """The platform's own provider records, recovered from the call log.

    ``find_provider`` logs the whole record the clinic returned — name,
    specialty, per-site schedules, insurers, leave — so this is a real roster
    rather than an approximation of one.

    It matters because the offline fallback is not real: ``vortex/clinic/
    fixtures.py`` carries seven providers to the platform's twelve, and gives
    PR03 a different name and specialty. A visit booked with a doctor the
    catalogue has never heard of has no grid to hang on, so it vanishes from
    the Agenda — which is most of the real bookings, not a few of them.
    """
    out: dict[str, ProviderRecord] = {}
    for event in events:
        if event.get("kind") != "tool.returned" or event.get("tool") != "find_provider":
            continue
        row = (event.get("result") or {}).get("provider")
        if not isinstance(row, dict) or not row.get("provider_id"):
            continue
        provider_id = str(row["provider_id"])
        if provider_id in out:
            continue
        try:
            out[provider_id] = ProviderRecord.model_validate(row)
        except ValidationError:
            continue
    return list(out.values())


def provider_names_from_events(events: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """``provider_id`` -> (name, specialty_id) as ``find_slots`` reported it.

    A thinner source than ``providers_from_events`` — a slot names its doctor
    but not their schedules, so this cannot put a missing doctor on the board.
    It can correct one already there: the fixtures call PR01 "Dra. Ortiz"
    where the clinic calls her "Dra. Carmen Ortiz Vidal", and the name is what
    the screen shows and what a receptionist would say out loud.
    """
    out: dict[str, tuple[str, str]] = {}
    for event in events:
        if event.get("kind") != "tool.returned" or event.get("tool") != "find_slots":
            continue
        for slot in (event.get("result") or {}).get("slots") or []:
            if not isinstance(slot, dict):
                continue
            provider_id = str(slot.get("provider_id") or "")
            name = str(slot.get("provider_name") or "")
            if provider_id and name and provider_id not in out:
                out[provider_id] = (name, str(slot.get("specialty_id") or ""))
    return out


def appointment_types_from_events(events: list[dict[str, Any]]) -> list[AppointmentTypeRecord]:
    """Appointment types the log has seen offered, with their real durations.

    ``find_slots`` names a slot's type and how long it runs but never the
    type's label, so ``name`` is left empty and the grid falls back to
    ``_pretty_id``. The duration is the point: without it an orthopaedic first
    visit draws as one 15-minute step instead of the three it occupies.
    """
    seen: dict[str, AppointmentTypeRecord] = {}
    for event in events:
        if event.get("kind") != "tool.returned" or event.get("tool") != "find_slots":
            continue
        for slot in (event.get("result") or {}).get("slots") or []:
            if not isinstance(slot, dict):
                continue
            type_id = str(slot.get("appointment_type_id") or "")
            if not type_id or type_id in seen:
                continue
            seen[type_id] = AppointmentTypeRecord(
                appointment_type_id=type_id,
                name="",
                specialty_id=slot.get("specialty_id") or None,
                duration_minutes=int(slot.get("duration_minutes") or 15),
            )
    return list(seen.values())


def catalogue_with_log_roster(catalogue: Catalogue, events: list[dict[str, Any]]) -> Catalogue:
    """``catalogue`` with every provider and type the log knows folded in.

    The log wins on collision: a record straight from ``GET /clinic`` via
    ``find_provider`` is the platform's answer, where the same id in the
    fixtures is a stand-in written before the real roster was known. A
    catalogue that is already live simply gets nothing it does not have.
    """
    providers = {row.provider_id: row for row in catalogue.providers}
    full = providers_from_events(events)
    for row in full:
        providers[row.provider_id] = row
    # Names for the doctors the log never looked up in full but did offer a
    # slot with. Only the fields a slot actually carries are touched, so a
    # stand-in keeps its schedules and becomes reachable under its real name.
    recovered = {row.provider_id for row in full}
    for provider_id, (name, specialty_id) in provider_names_from_events(events).items():
        row = providers.get(provider_id)
        if row is None or provider_id in recovered:
            continue
        providers[provider_id] = row.model_copy(
            update={"name": name, "specialty_id": specialty_id or row.specialty_id}
        )
    types = {row.appointment_type_id: row for row in catalogue.appointment_types}
    for row in appointment_types_from_events(events):
        types.setdefault(row.appointment_type_id, row)
    return catalogue.model_copy(
        update={"providers": list(providers.values()), "appointment_types": list(types.values())}
    )


def catalogue_with_appointment_roster(catalogue: Catalogue, appointments: list[Any]) -> Catalogue:
    """``catalogue`` with every provider a real ``public.appointments`` row
    names but the catalogue does not already know by id.

    ``catalogue_with_log_roster`` closes the same gap from ``find_slots``
    transcript events, which misses a provider entirely when a call never
    logged that tool under that exact name (a stub pipeline, an older
    transcript, a booking ``database/hooks.py`` wrote straight through). An
    appointment already carries its provider's id, name, specialty and site
    with no tool-log dependency at all — the most direct "the catalogue
    never heard of this doctor" fix there is, and the one
    ``service_occupancy``'s Gynaecology case ultimately needs: a booked
    appointment is proof a doctor exists even when nothing in the log ever
    asked ``find_slots`` for them.
    """
    providers = {row.provider_id: row for row in catalogue.providers}
    for appt in appointments:
        provider_id = str(getattr(appt, "provider_id", None) or "")
        specialty_id = getattr(appt, "specialty_id", None)
        if not provider_id or not specialty_id or provider_id in providers:
            continue
        site_id = getattr(appt, "site_id", None)
        providers[provider_id] = ProviderRecord(
            provider_id=provider_id,
            name=str(getattr(appt, "provider_name", None) or provider_id),
            specialty_id=str(specialty_id),
            specialty_name=str(getattr(appt, "specialty_name", None) or ""),
            location_ids=[str(site_id)] if site_id else [],
        )
    return catalogue.model_copy(update={"providers": list(providers.values())})


def load_database_agenda() -> tuple[list[Any], dict[str, str]]:
    """Open appointments and their call ids, or ``([], {})`` if unavailable.

    Late import and broad catch for the same reason the wall API reads
    ``wall_cancellations`` that way: an unreachable store must never blank
    the diary.
    """
    try:
        from database import db

        return db.list_appointments(), db.call_id_by_appointment()
    except Exception:
        return [], {}


def load_agenda_bookings(catalogue: Catalogue) -> dict[BookingKey, Booking]:
    """Taken slots for the Clinic View.

    ``public.appointments`` first: the line writes a row there as each
    BOOK/CANCEL/RESCHEDULE lands, so it holds the real clinic's own visits
    with the real providers and sites on them.

    An empty table — a fresh clone, or no store configured at all — falls
    back to the synthetic pack below, so the board shows a populated diary
    either way rather than an empty grid.
    """
    rows, call_ids = load_database_agenda()
    if rows:
        return bookings_from_rows(rows, call_ids, catalogue=catalogue)
    return load_pack_bookings(catalogue)


def load_pack_bookings(catalogue: Catalogue) -> dict[BookingKey, Booking]:
    """Taken slots from fixtures, the synthetic pack, then the pack's logs.

    Per-patient clinic lookups miss pack rows with an empty ``patient_id``.
    Reading ``appointments.json`` whole (and filling a missing doctor from the
    catalogue) is what puts those visits on the board.
    """
    from vortex.clinic import fixtures
    from vortex.clinic.client import _adapt_appointment

    extra = [Appointment.model_validate(_adapt_appointment(row)) for row in fixtures.APPOINTMENTS]
    bookings = bookings_from_appointments(extra)
    for booking in appointment_index().values():
        placed = assign_provider(catalogue, booking)
        if not placed.provider_id:
            continue
        bookings[_key(placed.provider_id, placed.location_id, placed.start)] = placed
    return bookings_from_events(
        load_source_events(),
        {row.appointment_id: row for row in bookings.values() if row.appointment_id},
        base=bookings,
    )


def bookings_from_events(
    events: list[dict[str, Any]],
    appt_index: dict[str, Booking] | None = None,
    *,
    base: dict[BookingKey, Booking] | None = None,
) -> dict[BookingKey, Booking]:
    """Replay the log's submitted actions into the set of taken slots.

    Events are read oldest first, so applying them in order is the diary's own
    history: a BOOK takes a slot, a CANCEL frees the one its ``appointment_id``
    names, a RESCHEDULE frees the old slot and takes the new one. CANCEL and the
    old leg of a RESCHEDULE carry no slot of their own, so they are resolved
    against the bookings this replay has already placed, then against
    ``appt_index`` (the pre-existing appointments from the pack). A cancel for
    an appointment with no known provider simply frees nothing.
    """
    appt_index = dict(appt_index or {})
    bookings: dict[BookingKey, Booking] = dict(base or {})
    replayed: dict[str, Booking] = {}
    for booking in bookings.values():
        if booking.appointment_id:
            appt_index.setdefault(booking.appointment_id, booking)
            replayed.setdefault(booking.appointment_id, booking)
    for event in events:
        if event.get("kind") != "submit.result":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        action = str(payload.get("action") or "").upper()
        if action not in _DIARY_ACTIONS:
            continue
        call_id = str(event.get("call_id") or "")
        appointment_id = str(payload.get("appointment_id") or "")
        if action in {"CANCEL", "RESCHEDULE"}:
            existing = replayed.pop(appointment_id, None) or appt_index.get(appointment_id)
            if existing is not None:
                bookings.pop(_key(existing.provider_id, existing.location_id, existing.start), None)
        if action in {"BOOK", "RESCHEDULE"}:
            booked = _apply_book(bookings, payload, call_id, appointment_id=appointment_id)
            if booked is not None and appointment_id:
                replayed[appointment_id] = booked
    return bookings


def cancel_key(provider_id: str, location_id: str, slot_start: Any) -> BookingKey | None:
    """The ``BookingKey`` a wall-cancellation row names — the same triple the
    diary itself keys bookings on. ``slot_start`` is an ISO string or a
    datetime; ``None`` when it cannot be parsed."""
    start = _parse_dt(slot_start)
    if start is None or not provider_id:
        return None
    return _key(provider_id, location_id, start)


def drop_cancelled(
    bookings: dict[BookingKey, Booking], cancelled: set[BookingKey]
) -> dict[BookingKey, Booking]:
    """The bookings minus every slot the control centre cancelled by hand.

    Same effect as a CANCEL event in the log — the slot reads free — but the
    source is ``wall_cancellations`` in the product database, not the event
    stream. A fresh copy; ``bookings`` is not mutated.
    """
    if not cancelled:
        return bookings
    return {key: booking for key, booking in bookings.items() if key not in cancelled}


def _booked_cell(booking: Booking, start: datetime, location_id: str) -> CalendarCell:
    return CalendarCell(
        start=start,
        status="booked",
        patient_id=booking.patient_id,
        appointment_type_id=booking.appointment_type_id,
        location_id=location_id,
        call_id=booking.call_id,
        provider_id=booking.provider_id,
        appointment_id=booking.appointment_id,
    )


def _cells_for_day(
    provider_id: str,
    schedules: list[Any],
    day: date,
    step: timedelta,
    bookings: dict[BookingKey, Booking],
    day_bookings: list[Booking],
) -> list[CalendarCell]:
    """The doctor's steps on ``day``: the open scaffold, plus any booked slot.

    The scaffold is one free (or booked) cell per open 15-minute interval. On
    top of it, any booking for this doctor and day that did not fall on a
    scheduled step is still shown - a slot at a site or hour the offline
    catalogue does not know about, or a doctor with no schedule offline at all.
    Booked slots are never hidden by a catalogue that disagrees with the log.
    """
    cells: list[CalendarCell] = []
    consumed: set[BookingKey] = set()
    for schedule in schedules:
        for interval in schedule.hours:
            if interval.weekday != day.weekday():
                continue
            cursor = datetime.combine(day, interval.opens, tzinfo=MADRID)
            closes = datetime.combine(day, interval.closes, tzinfo=MADRID)
            while cursor < closes:
                key = _key(provider_id, schedule.location_id, cursor)
                booking = bookings.get(key)
                if booking is not None:
                    consumed.add(key)
                    cells.append(_booked_cell(booking, cursor, schedule.location_id))
                else:
                    cells.append(
                        CalendarCell(start=cursor, status="free", location_id=schedule.location_id)
                    )
                cursor += step
    for booking in day_bookings:
        key = _key(booking.provider_id, booking.location_id, booking.start)
        if key in consumed:
            continue
        consumed.add(key)
        cells.append(_booked_cell(booking, booking.start, booking.location_id))
    cells.sort(key=lambda cell: (cell.start, cell.location_id))
    return cells


def grid_signature(calendars: list[DoctorCalendar]) -> tuple:
    """A fingerprint of everything the grids show: each cell's minute and state.

    The view redraws only when this changes. Totals are not enough: a reschedule
    moves a booking inside one doctor's window while the booked count, the
    capacity and the day count all stay the same, and the old slot would stay on
    screen.
    """
    return tuple(
        (
            calendar.provider_id,
            tuple(
                (day.day, tuple((cell.start, cell.status) for cell in day.cells))
                for day in calendar.days
            ),
        )
        for calendar in calendars
    )


def build_calendars(
    catalogue: Catalogue,
    bookings: dict[BookingKey, Booking],
    *,
    start_from: date | None = None,
    days_window: int | None = None,
) -> list[DoctorCalendar]:
    """A calendar per doctor over the visible window, booked slots filled in.

    The grid spans ``days_window`` days from ``start_from`` (defaults: the whole
    bookable window from the first bookable day), clamped to the catalogue's
    bookable window. Closure days are dropped, and a day with neither open hours
    nor a booking is dropped too, so each doctor's grid shows only their days.

    A doctor the log books but the offline catalogue does not know still gets a
    calendar (named by ``provider_id``), so no booking is silently lost. Live,
    where the catalogue and the log are the same clinic, that branch is unused.
    """
    start = start_from or catalogue.bookable_from or date.today()
    end = catalogue.bookable_to
    if days_window is not None:
        window_end = start + timedelta(days=days_window - 1)
        end = min(end, window_end) if end else window_end
    if end is None or end < start:
        end = start

    closures = set(catalogue.closure_days)
    step = timedelta(minutes=catalogue.slot_minutes or 15)

    # Bookings inside the window, grouped by provider then day, so a booking is
    # shown even when it does not land on a scheduled step.
    in_window: dict[str, dict[date, list[Booking]]] = {}
    for booking in bookings.values():
        day = booking.start.astimezone(MADRID).date()
        if day < start or day > end or day in closures:
            continue
        in_window.setdefault(booking.provider_id, {}).setdefault(day, []).append(booking)

    known_ids = {provider.provider_id for provider in catalogue.providers}
    ordered = sorted(catalogue.providers, key=lambda p: p.name.lower())
    unknown_ids = sorted(pid for pid in in_window if pid and pid not in known_ids)

    calendars: list[DoctorCalendar] = []
    for provider in ordered:
        calendars.append(
            _one_calendar(
                provider_id=provider.provider_id,
                name=provider.name,
                specialty=provider.specialty_name or provider.specialty_id,
                specialty_id=provider.specialty_id,
                location_ids=list(provider.location_ids),
                schedules=list(provider.schedules),
                start=start,
                end=end,
                step=step,
                closures=closures,
                bookings=bookings,
                day_bookings=in_window.get(provider.provider_id, {}),
            )
        )
    for provider_id in unknown_ids:
        calendars.append(
            _one_calendar(
                provider_id=provider_id,
                name=provider_id,
                specialty="",
                specialty_id="",
                location_ids=[],
                schedules=[],
                start=start,
                end=end,
                step=step,
                closures=closures,
                bookings=bookings,
                day_bookings=in_window.get(provider_id, {}),
            )
        )
    return calendars


def _one_calendar(
    *,
    provider_id: str,
    name: str,
    specialty: str,
    specialty_id: str,
    location_ids: list[str],
    schedules: list[Any],
    start: date,
    end: date,
    step: timedelta,
    closures: set[date],
    bookings: dict[BookingKey, Booking],
    day_bookings: dict[date, list[Booking]],
) -> DoctorCalendar:
    days: list[DoctorDay] = []
    cursor = start
    while cursor <= end:
        if cursor not in closures:
            cells = _cells_for_day(
                provider_id, schedules, cursor, step, bookings, day_bookings.get(cursor, [])
            )
            if cells:
                days.append(DoctorDay(day=cursor, cells=cells))
        cursor += timedelta(days=1)
    return DoctorCalendar(
        provider_id=provider_id,
        name=name,
        specialty=specialty,
        specialty_id=specialty_id,
        location_ids=location_ids,
        days=days,
    )


# ---------------------------------------------------------------------------
# IO helpers (the view's default wiring; the tests stay on the pure builders)
# ---------------------------------------------------------------------------

#: The isolated synthetic-data pack at the repo root. Holds the pre-existing
#: diaries (``appointments.json``) and one per-problem call log under ``logs/``.
SYNTHETIC_DATA_DIR = REPO_ROOT / "synthetic-data"


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    """A ``*.json`` list (or a ``{items: [...]}`` wrapper), empty if missing."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("appointments", "patients", "items"):
            items = payload.get(key)
            if isinstance(items, list):
                return items
    return []


def appointment_index(rows: list[dict[str, Any]] | None = None) -> dict[str, Booking]:
    """``appointment_id`` -> its slot, so CANCEL/RESCHEDULE can free the old one.

    Reads ``synthetic-data/appointments.json`` unless ``rows`` is given.
    """
    if rows is None:
        rows = _load_json_list(SYNTHETIC_DATA_DIR / "appointments.json")
    index: dict[str, Booking] = {}
    for row in rows:
        appointment_id = str(row.get("appointment_id") or "")
        start = _parse_dt(row.get("start_time"))
        if not appointment_id or start is None:
            continue
        index[appointment_id] = Booking(
            provider_id=str(row.get("provider_id") or ""),
            location_id=str(row.get("location_id") or ""),
            start=start.replace(second=0, microsecond=0),
            patient_id=str(row.get("patient_id") or ""),
            appointment_type_id=str(row.get("appointment_type_id") or ""),
            appointment_id=appointment_id,
        )
    return index


def _synthetic_log_files() -> list[Path]:
    """The per-problem logs in the pack, minus any rolled-up ``all.jsonl``."""
    logs_dir = SYNTHETIC_DATA_DIR / "logs"
    if not logs_dir.exists():
        return []
    return sorted(p for p in logs_dir.glob("*.jsonl") if p.name != "all.jsonl")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """A CallLog-shaped fixture file. Only ``synthetic-data/`` is read this
    way — real call events live in Postgres, never on disk."""
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def load_source_events(limit: int = 5000) -> list[dict[str, Any]]:
    """Log events to fill the calendar from, oldest first.

    Default: every per-problem log in ``synthetic-data/logs/``. Set
    ``VORTEX_CALENDAR_LOG`` to a single CallLog-shaped JSONL fixture to read
    that instead, and the same grid fills from it.

    The sort is by timestamp and stable, so the events of one call keep the
    order they were written even when the whole pack shares one instant.
    """
    override = os.environ.get("VORTEX_CALENDAR_LOG")
    paths = [Path(override)] if override else _synthetic_log_files()
    events: list[dict[str, Any]] = []
    for path in paths:
        if path.exists():
            events.extend(_read_jsonl(path))
    events.sort(key=lambda event: str(event.get("ts") or ""))
    return events[-limit:] if limit else events


def _full_name(row: dict[str, Any]) -> str:
    parts = (
        str(row.get("given_name") or "").strip(),
        str(row.get("first_surname") or "").strip(),
        str(row.get("second_surname") or "").strip(),
    )
    return " ".join(p for p in parts if p)


def patient_index(rows: list[dict[str, Any]] | None = None) -> dict[str, PatientBrief]:
    """``patient_id`` -> roster fields for the briefing card.

    Reads ``synthetic-data/patients.json`` unless ``rows`` is given. Falls back
    to ``fixtures.PATIENTS`` when the pack is missing, so a local board without
    hydrate still names the published personas.
    """
    if rows is None:
        rows = _load_json_list(SYNTHETIC_DATA_DIR / "patients.json")
        if not rows:
            from vortex.clinic import fixtures

            rows = list(fixtures.PATIENTS)
        else:
            from vortex.clinic import fixtures

            extra = {p["patient_id"]: p for p in fixtures.PATIENTS}
            rows = [
                {**row, "note": extra[pid]["note"]}
                if (pid := str(row.get("patient_id") or "")) in extra and extra[pid].get("note")
                else row
                for row in rows
            ]
    index: dict[str, PatientBrief] = {}
    for row in rows:
        patient_id = str(row.get("patient_id") or "")
        if not patient_id:
            continue
        index[patient_id] = PatientBrief(
            patient_id=patient_id,
            full_name=_full_name(row) or patient_id,
            phone=str(row.get("phone") or ""),
            insurer=str(row.get("insurer") or ""),
            note=str(row.get("note") or ""),
            has_visited_before=bool(row.get("has_visited_before")),
            sex=str(row.get("sex") or ""),
            date_of_birth=str(row.get("date_of_birth") or ""),
        )
    return index


def patient_index_from_records(records: list[PatientRecord]) -> dict[str, PatientBrief]:
    """Roster fields from ``GET /directory`` records."""
    index: dict[str, PatientBrief] = {}
    for record in records:
        born = record.date_of_birth.isoformat() if record.date_of_birth else ""
        index[record.patient_id] = PatientBrief(
            patient_id=record.patient_id,
            full_name=record.full_name or record.patient_id,
            phone=record.phone,
            insurer=record.insurer,
            note=record.note,
            has_visited_before=record.has_visited_before,
            sex=record.sex,
            date_of_birth=born,
        )
    return index


def _pretty_id(raw: str) -> str:
    return raw.replace("_", " ").strip()


#: Only what changes how the doctor treats the person in the room.
#: Dropped on purpose: the_questions, when_exactly, simple_booking, no_slot_free,
#: noise, triage, difficult_caller (visit doubts, slot hunt, go slower on the phone).
_DOCTOR_NOTES: dict[str, str] = {
    "languages": "Quiere la consulta en un idioma concreto.",
    "the_new_patient": "Primera vez en la clínica.",
    "the_rules": "Revisa edad, seguro o derivación antes de proceder.",
}


def week_start(day: date) -> date:
    """Monday of the ISO week that contains ``day``."""
    return day - timedelta(days=day.weekday())


def week_dates(monday: date) -> list[date]:
    """Seven days, Monday through Sunday."""
    return [monday + timedelta(days=i) for i in range(7)]


def month_start(day: date) -> date:
    """First calendar day of the month that contains ``day``."""
    return day.replace(day=1)


def month_weeks(focus: date) -> list[list[date]]:
    """Weeks that cover ``focus``'s month, padded like a wall calendar."""
    first = month_start(focus)
    if first.month == 12:
        last = date(first.year, 12, 31)
    else:
        last = date(first.year, first.month + 1, 1) - timedelta(days=1)
    start = week_start(first)
    end = week_start(last) + timedelta(days=6)
    weeks: list[list[date]] = []
    cursor = start
    while cursor <= end:
        weeks.append(week_dates(cursor))
        cursor += timedelta(days=7)
    return weeks


def age_years(date_of_birth: str, today: date) -> str:
    """``"42 years"`` from an ISO date, or ``""`` if the date is missing or bad."""
    raw = (date_of_birth or "").strip()[:10]
    if not raw:
        return ""
    try:
        born = date.fromisoformat(raw)
    except ValueError:
        return ""
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if years < 0:
        return ""
    return f"{years} years"


def clinical_note(raw: str) -> str:
    """Strip pack prefixes. Prefer ``readable_note`` for the card the doctor sees."""
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("Fake record."):
        rest = text[len("Fake record.") :].strip()
        rest = re.sub(r"^Published cases?:\s*", "", rest, flags=re.IGNORECASE)
        return rest
    if text.startswith("Roster record."):
        families = re.findall(r"\b([a-z_]+)-[0-9a-f]{8,}", text)
        reasons: list[str] = []
        for family in families:
            line = _DOCTOR_NOTES.get(family)
            if line and line not in reasons:
                reasons.append(line)
        return " ".join(reasons)
    return text


def readable_note(raw: str) -> str:
    """What the doctor needs for the consult, never a recap of the phone call."""
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("Roster record."):
        return clinical_note(text)
    return _plain_visit_note(clinical_note(text))


def _plain_visit_note(cleaned: str) -> str:
    text = cleaned.strip()
    if not text:
        return ""
    body = text.rstrip(".")
    lower = body.casefold()
    bits: list[str] = []
    if "hard of hearing" in lower:
        bits.append("Hipoacusia: habla despacio.")
    if "dermatology referral" in lower:
        bits.append("Trae derivación a dermatología.")
    elif re.search(r"\bholds a .+ referral", lower):
        bits.append("Trae una derivación.")
    if "never seen" in lower:
        bits.append("No ha venido nunca a la clínica.")
    if lower.startswith("child"):
        return (body[0].upper() + body[1:] + ".") if not bits else " ".join(bits)
    return " ".join(bits)


def briefing_for(
    cell: CalendarCell,
    patients: dict[str, PatientBrief],
    *,
    location_names: dict[str, str] | None = None,
    type_names: dict[str, str] | None = None,
    plan_names: dict[str, str] | None = None,
) -> VisitBrief:
    """Join a booked cell to the roster. Unknown ids stay as ids, never guessed."""
    patient = patients.get(cell.patient_id)
    insurer_id = patient.insurer if patient else ""
    type_id = cell.appointment_type_id
    loc_id = cell.location_id
    today = cell.start.astimezone(MADRID).date()
    return VisitBrief(
        start=cell.start,
        patient_id=cell.patient_id,
        full_name=(patient.full_name if patient else "") or "",
        phone=patient.phone if patient else "",
        insurer=(plan_names or {}).get(insurer_id, insurer_id),
        note=readable_note(patient.note if patient else ""),
        has_visited_before=patient.has_visited_before if patient else False,
        appointment_type=(type_names or {}).get(type_id, _pretty_id(type_id)),
        appointment_type_id=type_id,
        location_id=loc_id,
        location_name=(location_names or {}).get(loc_id, loc_id),
        sex=patient.sex if patient else "",
        age=age_years(patient.date_of_birth if patient else "", today),
        provider_id=cell.provider_id,
        appointment_id=cell.appointment_id,
    )


def _roster_visit(brief: VisitBrief, patients: dict[str, PatientBrief]) -> bool:
    person = patients.get(brief.patient_id)
    return bool(person and (person.full_name or "").strip())


def _visit_row(
    brief: VisitBrief,
    *,
    date_iso: str,
    duration_minutes: int,
) -> dict[str, Any]:
    sex = (brief.sex or "").strip().upper()
    minutes = duration_minutes if duration_minutes > 0 else 15
    return {
        "date": date_iso,
        "time": brief.start.strftime("%H:%M"),
        "when": brief.start.strftime("%a %d/%m · %H:%M"),
        # The slot key a wall cancellation posts back: doctor + site + the
        # minute, plus the clinic's own appointment id when the visit has one.
        "slot": brief.start.isoformat(),
        "provider_id": brief.provider_id,
        "patient_id": brief.patient_id,
        "appointment_id": brief.appointment_id,
        "duration_minutes": minutes,
        "full_name": brief.full_name,
        "phone": brief.phone,
        "insurer": brief.insurer,
        "note": brief.note,
        "has_visited_before": brief.has_visited_before,
        "appointment_type": brief.appointment_type,
        "appointment_type_id": brief.appointment_type_id,
        "location_id": brief.location_id,
        "location_name": brief.location_name,
        "sex": "Mujer" if sex == "F" else "Hombre" if sex == "M" else brief.sex,
        "age": brief.age,
    }


def _type_duration(type_id: str, type_durations: dict[str, int] | None) -> int:
    minutes = (type_durations or {}).get(type_id, 15)
    return minutes if minutes > 0 else 15


_DOW_ES = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
_MONTH_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _booked_starts(
    day: date,
    slots: dict[time, CalendarCell],
    times: list[time],
    patients: dict[str, PatientBrief],
    brief_kw: dict[str, Any],
    type_durations: dict[str, int] | None,
) -> list[dict[str, Any]]:
    visits: list[dict[str, Any]] = []
    for slot in times:
        cell = slots.get(slot)
        if cell is None or cell.status != "booked":
            continue
        brief = briefing_for(cell, patients, **brief_kw)
        if not _roster_visit(brief, patients):
            continue
        minutes = _type_duration(cell.appointment_type_id, type_durations)
        visits.append(
            _visit_row(
                brief,
                date_iso=day.isoformat(),
                duration_minutes=minutes,
            )
        )
    visits.sort(key=lambda row: str(row["time"]))
    return visits


def match_doctors(calendars: list[DoctorCalendar], query: str) -> list[DoctorCalendar]:
    """Name lookup for the diary login. Empty query matches nobody."""
    needle = (query or "").strip().casefold()
    if not needle:
        return []
    exact = [c for c in calendars if c.name.casefold() == needle]
    if exact:
        return exact
    return [c for c in calendars if needle in c.name.casefold()]


def suggest_doctors(
    calendars: list[DoctorCalendar], query: str, *, limit: int = 12
) -> dict[str, Any]:
    """Typeahead hits. Empty query returns nobody — never dump the roster."""
    found = match_doctors(calendars, query)
    return {
        "ok": True,
        "doctors": [
            {"name": calendar.name, "specialty": calendar.specialty} for calendar in found[:limit]
        ],
    }


def agenda_options(catalogue: Catalogue) -> dict[str, Any]:
    """Dropdown values that already exist in the clinic catalogue."""
    doctors = [
        {
            "id": provider.provider_id,
            "name": provider.name,
            "specialty": provider.specialty_name or provider.specialty_id,
            "specialty_id": provider.specialty_id,
        }
        for provider in sorted(catalogue.providers, key=lambda row: row.name.casefold())
    ]
    sites = [{"id": loc.location_id, "name": loc.name} for loc in catalogue.locations]
    specialties = [{"id": row.specialty_id, "name": row.name} for row in catalogue.specialties]
    if not specialties:
        seen: dict[str, str] = {}
        for provider in catalogue.providers:
            if provider.specialty_id and provider.specialty_id not in seen:
                seen[provider.specialty_id] = provider.specialty_name or provider.specialty_id
        specialties = [{"id": key, "name": label} for key, label in seen.items()]
    # A type recovered from the log has its real duration but no label — the
    # platform sends one only in the catalogue. Same ``_pretty_id`` fallback a
    # booked cell already uses, so the dropdown never carries a blank option.
    types = [
        {
            "id": row.appointment_type_id,
            "name": row.name or _pretty_id(row.appointment_type_id),
        }
        for row in catalogue.appointment_types
    ]
    return {
        "ok": True,
        "doctors": doctors,
        "sites": sites,
        "specialties": specialties,
        "types": types,
    }


def clamp_week(monday: date, calendar: DoctorCalendar) -> date:
    """Keep ``monday`` inside the weeks this doctor's grid actually spans."""
    if not calendar.days:
        return monday
    first = week_start(calendar.days[0].day)
    last = week_start(calendar.days[-1].day)
    if monday < first:
        return first
    if monday > last:
        return last
    return monday


def doctor_agenda(
    calendars: list[DoctorCalendar],
    patients: dict[str, PatientBrief],
    *,
    name: str,
    today: date,
    week: date | None = None,
    month: date | None = None,
    location_names: dict[str, str] | None = None,
    type_names: dict[str, str] | None = None,
    type_durations: dict[str, int] | None = None,
    plan_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """JSON payload for the Clinic View diary. Never returns a doctor catalogue."""
    found = match_doctors(calendars, name)
    if not found:
        return {"ok": False, "error": "no_match"}
    if len(found) > 1:
        return {"ok": False, "error": "ambiguous"}
    calendar = found[0]
    monday = clamp_week(week_start(week or today), calendar)
    first_week = week_start(calendar.days[0].day) if calendar.days else monday
    last_week = week_start(calendar.days[-1].day) if calendar.days else monday
    days = week_dates(monday)
    by_day: dict[date, dict[time, CalendarCell]] = {
        day.day: {cell.start.time(): cell for cell in day.cells} for day in calendar.days
    }
    times = [slot.strftime("%H:%M") for slot in calendar.times]
    brief_kw = {
        "location_names": location_names,
        "type_names": type_names,
        "plan_names": plan_names,
    }
    columns = []
    for day in days:
        slots = by_day.get(day, {})
        cells = []
        active_until: datetime | None = None
        active_visit: dict[str, Any] | None = None
        for slot in calendar.times:
            cell = slots.get(slot)
            cursor = datetime.combine(day, slot, tzinfo=MADRID)
            visit = None
            part = ""
            if cell is not None and cell.status == "booked":
                minutes = _type_duration(cell.appointment_type_id, type_durations)
                brief = briefing_for(cell, patients, **brief_kw)
                visit = (
                    _visit_row(
                        brief,
                        date_iso=day.isoformat(),
                        duration_minutes=minutes,
                    )
                    if _roster_visit(brief, patients)
                    else None
                )
                status = "booked"
                part = "start"
                active_until = cursor + timedelta(minutes=minutes)
                active_visit = visit
            elif (
                active_until is not None
                and active_visit is not None
                and cursor < active_until
                and cell is not None
            ):
                status = "booked"
                visit = active_visit
                part = "cont"
            elif cell is None:
                status = "off"
                if active_until is not None and cursor >= active_until:
                    active_until = None
                    active_visit = None
            else:
                status = "free"
                if active_until is not None and cursor >= active_until:
                    active_until = None
                    active_visit = None
            cells.append(
                {
                    "time": slot.strftime("%H:%M"),
                    "status": status,
                    "part": part,
                    "visit": visit,
                }
            )
        columns.append(
            {
                "date": day.isoformat(),
                "label": _DOW_ES[day.weekday()],
                "day": day.strftime("%d/%m"),
                "today": day == today,
                "cells": cells,
            }
        )
    visits = _booked_starts(
        today,
        by_day.get(today, {}),
        calendar.times,
        patients,
        brief_kw,
        type_durations,
    )
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        week_label = f"{monday.strftime('%d')}–{sunday.strftime('%d %b')}"
    else:
        week_label = f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b')}"
    focus = month_start(month or week or today)
    if calendar.days:
        first_month = month_start(calendar.days[0].day)
        last_month = month_start(calendar.days[-1].day)
        if focus < first_month:
            focus = first_month
        if focus > last_month:
            focus = last_month
    weeks = []
    for row in month_weeks(focus):
        week_row = []
        for day in row:
            week_row.append(
                {
                    "date": day.isoformat(),
                    "day": day.day,
                    "in_month": day.month == focus.month,
                    "today": day == today,
                    "visits": _booked_starts(
                        day,
                        by_day.get(day, {}),
                        calendar.times,
                        patients,
                        brief_kw,
                        type_durations,
                    ),
                }
            )
        weeks.append(week_row)
    month_label = f"{_MONTH_ES[focus.month - 1].capitalize()} {focus.year}"
    sites = [
        {"id": loc_id, "name": (location_names or {}).get(loc_id, loc_id)}
        for loc_id in calendar.location_ids
    ]
    return {
        "ok": True,
        "doctor": {"name": calendar.name, "specialty": calendar.specialty},
        "sites": sites,
        "week": monday.isoformat(),
        "week_label": week_label,
        "month": focus.isoformat(),
        "month_label": month_label,
        "today": today.isoformat(),
        "has_prev": monday > first_week,
        "has_next": monday < last_week,
        "times": times,
        "days": columns,
        "weeks": weeks,
        "visits": visits,
    }


def _day_visits(
    calendars: list[DoctorCalendar],
    day: date,
    patients: dict[str, PatientBrief],
    brief_kw: dict[str, Any],
    type_durations: dict[str, int] | None,
    *,
    require_name: bool,
    tag_provider: bool,
) -> list[dict[str, Any]]:
    """Booked visits on ``day`` across one or more doctor grids."""
    visits: list[dict[str, Any]] = []
    for calendar in calendars:
        day_obj = next((row for row in calendar.days if row.day == day), None)
        if day_obj is None:
            continue
        for cell in day_obj.cells:
            if cell.status != "booked":
                continue
            brief = briefing_for(cell, patients, **brief_kw)
            if require_name and not _roster_visit(brief, patients):
                continue
            minutes = _type_duration(cell.appointment_type_id, type_durations)
            row = _visit_row(
                brief,
                date_iso=day.isoformat(),
                duration_minutes=minutes,
            )
            if not str(row.get("full_name") or "").strip():
                row["full_name"] = "Cita"
            if tag_provider:
                row["provider_name"] = calendar.name
                row["provider_id"] = calendar.provider_id
                row["specialty"] = calendar.specialty
                row["specialty_id"] = calendar.specialty_id
            visits.append(row)
    visits.sort(key=lambda row: (str(row["time"]), str(row.get("provider_name") or "")))
    return visits


def clinic_agenda(
    calendars: list[DoctorCalendar],
    patients: dict[str, PatientBrief],
    *,
    name: str = "",
    specialty_id: str = "",
    today: date,
    week: date | None = None,
    month: date | None = None,
    location_names: dict[str, str] | None = None,
    type_names: dict[str, str] | None = None,
    type_durations: dict[str, int] | None = None,
    plan_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """JSON payload for Horarios. A doctor is optional; specialty is enough."""
    if (name or "").strip():
        return doctor_agenda(
            calendars,
            patients,
            name=name,
            today=today,
            week=week,
            month=month,
            location_names=location_names,
            type_names=type_names,
            type_durations=type_durations,
            plan_names=plan_names,
        )
    chosen = [
        calendar
        for calendar in calendars
        if not specialty_id or calendar.specialty_id == specialty_id
    ]
    brief_kw = {
        "location_names": location_names,
        "type_names": type_names,
        "plan_names": plan_names,
    }
    span = sorted({day.day for calendar in chosen for day in calendar.days})
    monday = week_start(week or today)
    if span:
        first_week = week_start(span[0])
        last_week = week_start(span[-1])
        if monday < first_week:
            monday = first_week
        if monday > last_week:
            monday = last_week
    else:
        first_week = last_week = monday
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        week_label = f"{monday.strftime('%d')}–{sunday.strftime('%d %b')}"
    else:
        week_label = f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b')}"
    focus = month_start(month or week or today)
    if span:
        first_month = month_start(span[0])
        last_month = month_start(span[-1])
        if focus < first_month:
            focus = first_month
        if focus > last_month:
            focus = last_month
    weeks = []
    for row in month_weeks(focus):
        week_row = []
        for day in row:
            week_row.append(
                {
                    "date": day.isoformat(),
                    "day": day.day,
                    "in_month": day.month == focus.month,
                    "today": day == today,
                    "visits": _day_visits(
                        chosen,
                        day,
                        patients,
                        brief_kw,
                        type_durations,
                        require_name=False,
                        tag_provider=True,
                    ),
                }
            )
        weeks.append(week_row)
    month_label = f"{_MONTH_ES[focus.month - 1].capitalize()} {focus.year}"
    specialty_name = ""
    if specialty_id:
        specialty_name = next(
            (calendar.specialty for calendar in chosen if calendar.specialty),
            specialty_id,
        )
    location_ids: list[str] = []
    seen: set[str] = set()
    for calendar in chosen:
        for loc_id in calendar.location_ids:
            if loc_id in seen:
                continue
            seen.add(loc_id)
            location_ids.append(loc_id)
    sites = [
        {"id": loc_id, "name": (location_names or {}).get(loc_id, loc_id)}
        for loc_id in location_ids
    ]
    return {
        "ok": True,
        "doctor": {
            "name": specialty_name,
            "specialty": specialty_name,
        },
        "sites": sites,
        "week": monday.isoformat(),
        "week_label": week_label,
        "month": focus.isoformat(),
        "month_label": month_label,
        "today": today.isoformat(),
        "has_prev": monday > first_week,
        "has_next": monday < last_week,
        "times": [],
        "days": [],
        "weeks": weeks,
        "visits": _day_visits(
            chosen,
            today,
            patients,
            brief_kw,
            type_durations,
            require_name=False,
            tag_provider=True,
        ),
    }


_SUMMARY_CACHE: dict[str, str] = {}


def clear_summary_cache() -> None:
    """Tests reset the in-memory cache between cases."""
    _SUMMARY_CACHE.clear()


def _summary_text(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("summary_text") or "").strip()
    if isinstance(payload, list) and payload:
        return _summary_text(payload[0])
    return ""


def summarize_note(note: str, *, token: str = "", post: Any | None = None) -> str:
    """One-line summary of a receptionist note, or ``""`` to show the original.

    Skips the API when the note is already short, when there is no token, or
    when Hugging Face errors. ``post`` is the httpx-shaped caller; tests pass a
    stub so this stays offline.
    """
    text = (note or "").strip()
    if not text or not token:
        return ""
    if len(text.split()) < SHORT_NOTE_WORDS:
        return ""
    cached = _SUMMARY_CACHE.get(text)
    if cached is not None:
        return cached

    def _post(url: str, *, headers: dict[str, str], json: dict[str, str], timeout: float) -> Any:
        import httpx

        response = httpx.post(url, headers=headers, json=json, timeout=timeout)
        response.raise_for_status()
        return response.json()

    caller = post or _post
    try:
        payload = caller(
            HF_SUMMARIZE_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"inputs": text},
            timeout=3.0,
        )
    except Exception:
        return ""
    summary = _summary_text(payload)
    if summary:
        _SUMMARY_CACHE[text] = summary
    return summary
