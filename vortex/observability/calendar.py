"""Per-doctor calendars for the board.

Builds, for each provider, a day x time grid from the clinic catalogue
(opening hours, closure days, the bookable window) and fills the slots the call
log says were booked, moved or cancelled.

The log source is the synthetic-data pack by default
(``synthetic-data/logs/*.jsonl``). Set ``VORTEX_CALENDAR_LOG`` to point it at a
single live call log (``logs/calls.jsonl``) later - the grid fills from
whichever file it reads as more actions land.

The builders (``bookings_from_events``, ``build_calendars``) are pure: they take
data and return data, so the view and the tests share one code path. The two IO
helpers (``appointment_index``, ``load_source_events``) sit at the bottom.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from vortex.contract import MADRID, Catalogue
from vortex.observability.calllog import read_recent
from vortex.settings import REPO_ROOT

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
) -> None:
    """Place the slot a BOOK (or the new leg of a RESCHEDULE) names."""
    provider_id = str(payload.get("provider_id") or "")
    location_id = str(payload.get("location_id") or "")
    start = _parse_dt(payload.get("slot"))
    if not provider_id or start is None:
        return
    start = start.replace(second=0, microsecond=0)
    bookings[_key(provider_id, location_id, start)] = Booking(
        provider_id=provider_id,
        location_id=location_id,
        start=start,
        patient_id=str(payload.get("patient_id") or ""),
        appointment_type_id=str(payload.get("appointment_type_id") or ""),
        appointment_id=appointment_id,
        call_id=call_id,
    )


def bookings_from_events(
    events: list[dict[str, Any]],
    appt_index: dict[str, Booking] | None = None,
) -> dict[BookingKey, Booking]:
    """Replay the log's submitted actions into the set of taken slots.

    Events are read oldest first, so applying them in order is the diary's own
    history: a BOOK takes a slot, a CANCEL frees the one its ``appointment_id``
    names, a RESCHEDULE frees the old slot and takes the new one. CANCEL and the
    old leg of a RESCHEDULE carry no slot of their own, so they are resolved
    through ``appt_index`` (the pre-existing appointments from the pack). A
    cancel for an appointment with no known provider simply frees nothing.
    """
    appt_index = appt_index or {}
    bookings: dict[BookingKey, Booking] = {}
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
            existing = appt_index.get(appointment_id)
            if existing is not None:
                bookings.pop(_key(existing.provider_id, existing.location_id, existing.start), None)
        if action in {"BOOK", "RESCHEDULE"}:
            _apply_book(bookings, payload, call_id, appointment_id=appointment_id)
    return bookings


def _booked_cell(booking: Booking, start: datetime, location_id: str) -> CalendarCell:
    return CalendarCell(
        start=start,
        status="booked",
        patient_id=booking.patient_id,
        appointment_type_id=booking.appointment_type_id,
        location_id=location_id,
        call_id=booking.call_id,
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


def load_source_events(limit: int = 5000) -> list[dict[str, Any]]:
    """Log events to fill the calendar from, oldest first.

    Default: every per-problem log in ``synthetic-data/logs/``. Set
    ``VORTEX_CALENDAR_LOG`` to a single JSONL file (the live ``logs/calls.jsonl``)
    to read that instead, and the same grid fills from it as calls land.

    The sort is by timestamp and stable, so the events of one call keep the
    order they were written even when the whole pack shares one instant.
    """
    override = os.environ.get("VORTEX_CALENDAR_LOG")
    if override:
        return read_recent(Path(override), limit=limit)
    events: list[dict[str, Any]] = []
    for path in _synthetic_log_files():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    events.sort(key=lambda event: str(event.get("ts") or ""))
    return events[-limit:] if limit else events
