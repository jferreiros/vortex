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

from vortex import contract
from vortex.clinic.client import ClinicApiError
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


async def resolve_date(ctx: ToolContext, args: ResolveDateInput) -> ResolvedWindow:
    """Turn a colloquial phrase into a date window in Europe/Madrid.

    TODO(diary): cover the fixed vocabulary of problem 5 (tomorrow, the day
    after tomorrow, a week from today, in a fortnight, on Saturday morning,
    this coming <day>, first thing <day>, <day> afternoon, first thing on
    Monday the twelfth of October) plus explicit dates. Move a closed day to
    the next open day and set ``moved_from_closed_day``.
    """
    return await contract.stub_resolve_date(ctx, args)


async def find_slots(ctx: ToolContext, args: FindSlotsInput) -> AvailabilityResult:
    """Real availability from the clinic, filtered by the caller's constraints.

    TODO(diary): call ``ctx.clinic.availability(...)`` in spans of at most 14
    days, drop same-day slots, apply time_from/time_to, apply the language
    filter through the catalogue's provider languages, and carry ``blocked``
    and ``appointment_type`` through untouched.
    """
    return await contract.stub_find_slots(ctx, args)


async def list_appointments(ctx: ToolContext, args: ListAppointmentsInput) -> AppointmentList:
    """The patient's diary. ``upcoming`` is the only source of an appointment_id.

    TODO(diary): call ``ctx.clinic.appointments(patient_id, when=...)``.
    """
    return await contract.stub_list_appointments(ctx, args)


async def prepare_booking(ctx: ToolContext, args: PrepareBookingInput) -> BookingResult:
    """Build the ``BookAction`` for a chosen slot, or reject it.

    Every id on the action is copied verbatim from the slot ``/availability``
    offered: ``provider_id``, ``location_id``, ``appointment_type_id`` and the
    ``slot`` timestamp itself. Nothing is renamed and nothing is rebuilt by
    hand - the API compares ids exactly, so a hand-made type id fails even
    when time and duration match.

    Guards before building the action:

    - Nothing is booked on the day of the call. "Earliest" starts tomorrow,
      measured against ``ctx.now`` in Europe/Madrid, never the machine clock.
    - The slot must sit inside the catalogue's bookable window and not on a
      closure day.
    - The exact slot (provider, location, type, start) must still appear in
      the availability answer for that day and patient. A slot that is not
      there was never offered, so booking it would report ids the clinic
      does not recognise.
    """
    today = ctx.now.astimezone(MADRID).date()
    day = args.slot.start.astimezone(MADRID).date()
    if day <= today:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability",
                detail=f"same-day booking: slot {day} is not after the call day {today}",
            )
        )

    catalogue = await ctx.clinic.catalogue()
    if catalogue.bookable_from and day < catalogue.bookable_from:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability",
                detail=f"slot {day} is before the bookable window opens "
                f"({catalogue.bookable_from})",
            )
        )
    if catalogue.bookable_to and day > catalogue.bookable_to:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability",
                detail=f"slot {day} is after the bookable window closes ({catalogue.bookable_to})",
            )
        )
    if day in catalogue.closure_days:
        return BookingResult(
            rejection=Rejection(
                reason="clinic_closed",
                detail=f"slot {day} falls on a closure day",
            )
        )

    try:
        availability = await ctx.clinic.availability(
            date_from=day,
            date_to=day,
            provider_id=args.slot.provider_id,
            location_id=args.slot.location_id,
            patient_id=args.patient_id,
        )
    except ClinicApiError as exc:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability",
                detail=f"availability re-check failed: {exc}",
            )
        )
    offered = any(
        slot.start == args.slot.start
        and slot.provider_id == args.slot.provider_id
        and slot.location_id == args.slot.location_id
        and slot.appointment_type_id == args.slot.appointment_type_id
        for slot in availability.slots
    )
    if not offered:
        return BookingResult(
            rejection=Rejection(
                reason="no_availability",
                detail=(
                    f"slot {args.slot.start.isoformat()} with provider "
                    f"{args.slot.provider_id} at {args.slot.location_id} "
                    f"({args.slot.appointment_type_id}) is not in the "
                    "availability answer for that day"
                ),
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
