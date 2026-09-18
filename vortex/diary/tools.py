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
from vortex.contract import (
    AppointmentList,
    AvailabilityResult,
    BookingResult,
    CancelResult,
    FindSlotsInput,
    ListAppointmentsInput,
    PrepareBookingInput,
    PrepareCancelInput,
    PrepareRescheduleInput,
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

    TODO(diary): reject a same-day slot, a slot outside the bookable window,
    and a slot whose provider/location/type do not match the availability
    answer that offered it.
    """
    return await contract.stub_prepare_booking(ctx, args)


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
