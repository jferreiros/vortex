"""observability/calendar.py: the per-doctor grid and how the log fills it.

The builders are pure, so these tests hand them a tiny hand-built catalogue and
a list of log events and check the slots that come out. One integration test at
the end runs the real offline catalogue through the synthetic-data pack.
"""

from __future__ import annotations

from datetime import date, datetime, time

from vortex.clinic.client import FakeClinicClient
from vortex.contract import (
    MADRID,
    Catalogue,
    OpeningHours,
    ProviderRecord,
    ProviderSchedule,
)
from vortex.observability import calendar as cal

#: A provider who sits at Centro on Mondays only, 09:00-10:00: four 15-min steps.
_MONDAY = 0
_START = date(2026, 10, 5)  # a Monday
_FIESTA = date(2026, 10, 12)  # the next Monday, a published closure day


def _catalogue() -> Catalogue:
    provider = ProviderRecord(
        provider_id="PR01",
        name="Dra. Uno",
        specialty_id="general",
        specialty_name="General practice",
        location_ids=["centro"],
        schedules=[
            ProviderSchedule(
                location_id="centro",
                hours=[OpeningHours(weekday=_MONDAY, opens=time(9, 0), closes=time(10, 0))],
            )
        ],
    )
    return Catalogue(
        providers=[provider],
        bookable_from=_START,
        bookable_to=date(2026, 10, 31),
        closure_days=[_FIESTA],
        slot_minutes=15,
    )


def _slot(hour: int, minute: int) -> str:
    return datetime(2026, 10, 5, hour, minute, tzinfo=MADRID).isoformat()


def _book_event(hour: int, minute: int, *, patient: str = "P00001") -> dict:
    return {
        "kind": "submit.result",
        "call_id": "roster:x",
        "payload": {
            "action": "BOOK",
            "patient_id": patient,
            "provider_id": "PR01",
            "location_id": "centro",
            "appointment_type_id": "review",
            "slot": _slot(hour, minute),
        },
    }


def _appt(appointment_id: str, hour: int, minute: int) -> cal.Booking:
    return cal.Booking(
        provider_id="PR01",
        location_id="centro",
        start=datetime(2026, 10, 5, hour, minute, tzinfo=MADRID),
        appointment_id=appointment_id,
    )


def _only_calendar(events: list[dict], appt_index: dict | None = None) -> cal.DoctorCalendar:
    bookings = cal.bookings_from_events(events, appt_index or {})
    calendars = cal.build_calendars(_catalogue(), bookings, start_from=_START, days_window=8)
    assert len(calendars) == 1
    return calendars[0]


def _cell_at(calendar: cal.DoctorCalendar, hour: int, minute: int) -> cal.CalendarCell:
    day = next(d for d in calendar.days if d.day == _START)
    return next(c for c in day.cells if c.start.time() == time(hour, minute))


# ---- the empty grid -------------------------------------------------------


def test_grid_follows_open_hours_and_skips_closure_days() -> None:
    calendar = _only_calendar([])
    # Only the first Monday survives: the second (12 Oct) is a closure day.
    assert [d.day for d in calendar.days] == [_START]
    # 09:00-10:00 in 15-min steps is exactly four steps, none at or past 10:00.
    assert calendar.times == [time(9, 0), time(9, 15), time(9, 30), time(9, 45)]
    assert calendar.capacity == 4
    assert calendar.booked == 0
    assert all(cell.status == "free" for d in calendar.days for cell in d.cells)


# ---- BOOK -----------------------------------------------------------------


def test_book_fills_the_named_slot() -> None:
    calendar = _only_calendar([_book_event(9, 15, patient="P00007")])
    booked = _cell_at(calendar, 9, 15)
    assert booked.status == "booked"
    assert booked.patient_id == "P00007"
    assert booked.appointment_type_id == "review"
    assert calendar.booked == 1
    # The other three steps stay free.
    assert _cell_at(calendar, 9, 0).status == "free"


# ---- CANCEL ---------------------------------------------------------------


def test_cancel_frees_the_slot_via_appointment_id() -> None:
    events = [
        _book_event(9, 30),
        {
            "kind": "submit.result",
            "call_id": "roster:x",
            "payload": {"action": "CANCEL", "appointment_id": "A1"},
        },
    ]
    calendar = _only_calendar(events, {"A1": _appt("A1", 9, 30)})
    assert _cell_at(calendar, 9, 30).status == "free"
    assert calendar.booked == 0


# ---- RESCHEDULE -----------------------------------------------------------


def test_reschedule_moves_from_the_old_slot_to_the_new_one() -> None:
    events = [
        _book_event(9, 0),
        {
            "kind": "submit.result",
            "call_id": "roster:x",
            "payload": {
                "action": "RESCHEDULE",
                "appointment_id": "A2",
                "provider_id": "PR01",
                "location_id": "centro",
                "slot": _slot(9, 45),
            },
        },
    ]
    calendar = _only_calendar(events, {"A2": _appt("A2", 9, 0)})
    assert _cell_at(calendar, 9, 0).status == "free"
    assert _cell_at(calendar, 9, 45).status == "booked"
    assert calendar.booked == 1


# ---- the grid signature the view redraws on -------------------------------


def test_grid_signature_notices_a_moved_booking() -> None:
    """The view redraws only on a new signature, so a move must change it.

    Totals stay put when a booking moves inside the same doctor's window: same
    booked count, same capacity, same open days. Only the cells differ.
    """
    before = [_only_calendar([_book_event(9, 0)])]
    moved = [
        _only_calendar(
            [
                _book_event(9, 0),
                {
                    "kind": "submit.result",
                    "call_id": "roster:x",
                    "payload": {
                        "action": "RESCHEDULE",
                        "appointment_id": "A2",
                        "provider_id": "PR01",
                        "location_id": "centro",
                        "slot": _slot(9, 45),
                    },
                },
            ],
            {"A2": _appt("A2", 9, 0)},
        )
    ]
    assert before[0].booked == moved[0].booked
    assert before[0].capacity == moved[0].capacity
    assert len(before[0].days) == len(moved[0].days)
    assert cal.grid_signature(before) != cal.grid_signature(moved)


def test_grid_signature_is_stable_for_an_unchanged_grid() -> None:
    same = _only_calendar([_book_event(9, 30)])
    again = _only_calendar([_book_event(9, 30)])
    assert cal.grid_signature([same]) == cal.grid_signature([again])


# ---- non-diary verbs ------------------------------------------------------


def test_no_action_and_register_never_touch_a_calendar() -> None:
    events = [
        {"kind": "submit.result", "payload": {"action": "NO_ACTION", "reason": "out_of_scope"}},
        {"kind": "submit.result", "payload": {"action": "REGISTER", "new_patient": {}}},
    ]
    assert cal.bookings_from_events(events, {}) == {}


# ---- end to end, offline --------------------------------------------------


async def test_real_catalogue_fills_from_the_synthetic_pack() -> None:
    catalogue = await FakeClinicClient().catalogue()
    events = cal.load_source_events()
    if not events:
        # The pack is a generated artifact; skip cleanly if it is not present.
        import pytest

        pytest.skip("synthetic-data pack not generated")
    bookings = cal.bookings_from_events(events, cal.appointment_index())
    calendars = cal.build_calendars(catalogue, bookings)

    assert calendars, "expected one calendar per provider"
    # The roster BOOKs land on at least one doctor.
    assert any(c.booked for c in calendars)
    # The Fiesta Nacional is never an open day on any doctor's grid.
    fiesta = date(2026, 10, 12)
    assert all(d.day != fiesta for c in calendars for d in c.days)
    # No booked cell exceeds its doctor's capacity accounting.
    for c in calendars:
        assert c.booked <= c.capacity
