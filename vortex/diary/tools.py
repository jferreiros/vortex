"""diary/ tools - the agenda.

Owner: the diary lane. Replace each ``stub_*`` call with the real logic.
Keep the signatures exactly as ``vortex/contract.py`` declares them.

What the docs say this lane must get right (clinic docs, "Calendar"):

- Dates resolve against ``ctx.now`` (the moment the call connected, in
  Europe/Madrid). Never against the machine clock.
- Nothing is booked on the day of the call. "Earliest" starts tomorrow.
- Slots run 7 Sep - 16 Oct 2026 in 15-minute steps. /availability rejects a
  span longer than 14 days (422) and any date outside the window.
- Monday 12 October is closed. Only Centro opens on Saturday. Nothing opens
  on Sunday. Sur shuts Friday lunchtime.
- "Morning" is before 14:00; "afternoon" from 14:00.
- A weekday phrase is the first such weekday strictly after the call's day.
- The appointment type comes from /availability's ``appointment_type``, never
  from the caller. Submit the id on the slot.
- ``appointment_id`` comes only from /patients/{id}/appointments?when=upcoming.
- Spread the load: when several providers tie, prefer the least busy one,
  but the caller's ask always wins.
"""

from __future__ import annotations

import re
from datetime import date, time, timedelta

from vortex import contract
from vortex.contract import (
    MADRID,
    AppointmentList,
    AvailabilityResult,
    BookAction,
    BookingResult,
    CancelResult,
    FindSlotsInput,
    ListAppointmentsInput,
    PrepareBookingInput,
    PrepareCancelInput,
    PrepareRescheduleInput,
    Rejection,
    RescheduleResult,
    ResolveDateInput,
    ResolvedWindow,
    ToolContext,
)

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
    "twenty-first": 21, "twenty-second": 22, "twenty-third": 23, "twenty-fourth": 24,
    "twenty-fifth": 25, "twenty-sixth": 26, "twenty-seventh": 27, "twenty-eighth": 28,
    "twenty-ninth": 29, "thirtieth": 30, "thirty-first": 31,
}  # fmt: skip
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}  # fmt: skip
_MAX_SPAN_DAYS = 13  # date_to - date_from; the API's max span is 14 days inclusive
_EARLIEST_PHRASES = {"", "earliest", "the earliest", "the earliest available appointment"}


def _next_weekday(today: date, weekday: int) -> date:
    """The first ``weekday`` (0=Monday) strictly after ``today``."""
    delta = (weekday - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def _skip_closed(day: date, closure_days: set[date]) -> tuple[date, bool]:
    moved = False
    while day in closure_days:
        day += timedelta(days=1)
        moved = True
    return day, moved


async def resolve_date(ctx: ToolContext, args: ResolveDateInput) -> ResolvedWindow:
    """Turn a colloquial phrase into a date window in Europe/Madrid.

    A resolved day gets a week of slack on ``date_to`` so a caller's day that
    turns out closed *at a specific site* (Sur's Friday lunchtime, nothing
    Sunday anywhere — this tool takes no ``location_id``, so it cannot know
    that) still lets ``find_slots`` return the next real opening.
    ``moved_from_closed_day`` only covers what this tool can check directly:
    the one published network-wide closure day.
    """
    catalogue = await ctx.clinic.catalogue()
    closure_days = set(catalogue.closure_days)
    today = ctx.now.astimezone(MADRID).date()
    phrase = re.sub(r"\s+", " ", args.phrase.strip().lower())
    part_of_day = args.part_of_day

    day: date | None = None
    if phrase in _EARLIEST_PHRASES:
        day = today + timedelta(days=1)
    elif phrase == "tomorrow":
        day = today + timedelta(days=1)
    elif phrase == "the day after tomorrow":
        day = today + timedelta(days=2)
    elif phrase == "a week from today":
        day = today + timedelta(days=7)
    elif phrase == "in a fortnight":
        day = today + timedelta(days=14)
    elif m := re.fullmatch(r"first thing on (\w+) the ([\w-]+) of (\w+)", phrase):
        _, ordinal_word, month_word = m.groups()
        month, day_of_month = _MONTHS[month_word], _ORDINALS[ordinal_word]
        candidate = date(today.year, month, day_of_month)
        day = candidate if candidate > today else date(today.year + 1, month, day_of_month)
        part_of_day = part_of_day or "morning"
    elif m := re.fullmatch(r"(?:on )?(\w+) morning", phrase):
        day = _next_weekday(today, _WEEKDAYS.index(m.group(1)))
        part_of_day = part_of_day or "morning"
    elif m := re.fullmatch(r"this coming (\w+)", phrase):
        day = _next_weekday(today, _WEEKDAYS.index(m.group(1)))
    elif m := re.fullmatch(r"first thing (?:on )?(\w+)", phrase):
        day = _next_weekday(today, _WEEKDAYS.index(m.group(1)))
        part_of_day = part_of_day or "morning"
    elif m := re.fullmatch(r"(\w+) afternoon", phrase):
        day = _next_weekday(today, _WEEKDAYS.index(m.group(1)))
        part_of_day = part_of_day or "afternoon"

    if day is None:
        return ResolvedWindow(
            date_from=today,
            date_to=today,
            rejection=Rejection(
                reason="clinic_closed", detail=f"unrecognised phrase: {args.phrase!r}"
            ),
        )

    day, moved = _skip_closed(day, closure_days)
    date_to = day + timedelta(days=_MAX_SPAN_DAYS)
    if catalogue.bookable_to:
        date_to = min(date_to, catalogue.bookable_to)

    time_from = time_to = None
    if part_of_day == "morning":
        time_from, time_to = time(0, 0), time(14, 0)
    elif part_of_day == "afternoon":
        time_from, time_to = time(14, 0), time(23, 59)

    return ResolvedWindow(
        date_from=day,
        date_to=max(date_to, day),
        time_from=time_from,
        time_to=time_to,
        moved_from_closed_day=moved,
    )


async def find_slots(ctx: ToolContext, args: FindSlotsInput) -> AvailabilityResult:
    """Real availability from the clinic, filtered by the caller's constraints."""
    result = await ctx.clinic.availability(
        date_from=args.date_from,
        date_to=args.date_to,
        provider_id=args.provider_id,
        specialty_id=args.specialty_id,
        location_id=args.location_id,
        patient_id=args.patient_id,
        insurer=[args.insurer] if args.insurer else None,
    )

    today = ctx.now.astimezone(MADRID).date()
    slots = [s for s in result.slots if s.start.astimezone(MADRID).date() > today]

    if args.time_from is not None or args.time_to is not None:
        lo = args.time_from or time(0, 0)
        hi = args.time_to or time(23, 59)
        slots = [s for s in slots if lo <= s.start.astimezone(MADRID).time() <= hi]

    if args.language:
        catalogue = await ctx.clinic.catalogue()
        speaks = {p.provider_id for p in catalogue.providers if args.language in p.languages}
        slots = [s for s in slots if s.provider_id in speaks]

    slots.sort(key=lambda s: s.start)
    return AvailabilityResult(
        slots=slots, blocked=result.blocked, appointment_type=result.appointment_type
    )


async def list_appointments(ctx: ToolContext, args: ListAppointmentsInput) -> AppointmentList:
    """The patient's diary. ``upcoming`` is the only source of an appointment_id.

    TODO(diary): call ``ctx.clinic.appointments(patient_id, when=...)``.
    """
    return await contract.stub_list_appointments(ctx, args)


async def prepare_booking(ctx: ToolContext, args: PrepareBookingInput) -> BookingResult:
    """Build the ``BookAction`` for a chosen slot, or reject it."""
    today = ctx.now.astimezone(MADRID).date()
    slot_date = args.slot.start.astimezone(MADRID).date()
    if slot_date <= today:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability", detail="same-day booking is never accepted"
            )
        )
    catalogue = await ctx.clinic.catalogue()
    if catalogue.bookable_to and slot_date > catalogue.bookable_to:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability", detail="slot is outside the bookable window"
            )
        )
    return BookingResult(
        action=BookAction(
            patient_id=args.patient_id,
            provider_id=args.slot.provider_id,
            location_id=args.slot.location_id,
            appointment_type_id=args.slot.appointment_type_id,
            slot=args.slot.start,
            policy_id=args.policy_id,
        )
    )


async def prepare_reschedule(ctx: ToolContext, args: PrepareRescheduleInput) -> RescheduleResult:
    """Build the ``RescheduleAction``. A past visit cannot be moved.

    TODO(diary): check the appointment_id is an upcoming one of this patient.
    """
    return await contract.stub_prepare_reschedule(ctx, args)


async def prepare_cancel(ctx: ToolContext, args: PrepareCancelInput) -> CancelResult:
    """Build the ``CancelAction``. A past visit cannot be cancelled.

    TODO(diary): check the appointment_id is an upcoming one of this patient.
    """
    return await contract.stub_prepare_cancel(ctx, args)
