"""diary/: the agenda. Dates against ``ctx.now``, the closed-day moves, the
14:00 boundary, full-vs-shut, and the guards on an ``appointment_id``.

The eval harness covers the published English vocabulary case by case
(``evals/logic/cases/diary.yaml`` and the problem-5 probes). What lives here is
what the harness does not reach: the non-English phrases, and the reason each
guard returns when it refuses.
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path

import pytest

from vortex.clinic.client import FakeClinicClient
from vortex.contract import (
    MADRID,
    FindSlotsInput,
    ListAppointmentsInput,
    PrepareCancelInput,
    PrepareRescheduleInput,
    ResolveDateInput,
    Slot,
    ToolContext,
)
from vortex.diary.tools import (
    find_slots,
    list_appointments,
    prepare_cancel,
    prepare_reschedule,
    resolve_date,
)
from vortex.line.submit import DryRunSubmitClient
from vortex.observability.calllog import CallLog

#: Friday 18 September 2026, 09:00 Madrid: the moment the public cases anchor to.
NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)
PATIENT = "P00042"
CHILD = "P00107"


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        call_id="CA-diary",
        now=NOW,
        from_number="+34612345678",
        clinic=FakeClinicClient(),
        log=CallLog("CA-diary", tmp_path / "calls.jsonl"),
        submitter=DryRunSubmitClient(),
    )


async def _window(ctx: ToolContext, phrase: str, part: str | None = None):
    return await resolve_date(ctx, ResolveDateInput(phrase=phrase, part_of_day=part))


# ---- resolve_date ---------------------------------------------------------


async def test_a_weekday_is_the_first_one_strictly_after_the_call(ctx: ToolContext) -> None:
    """Said on a Friday, "this coming Friday" is a week away, not today."""
    window = await _window(ctx, "this coming Friday")
    assert window.date_from == date(2026, 9, 25)
    assert window.date_to == window.date_from  # one named day, one day wide


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("tomorrow", date(2026, 9, 19)),
        ("the day after tomorrow", date(2026, 9, 21)),  # Sunday: moved to Monday
        ("a week from today", date(2026, 9, 25)),
        ("in a fortnight", date(2026, 10, 2)),
    ],
)
async def test_the_published_offsets(ctx: ToolContext, phrase: str, expected: date) -> None:
    assert (await _window(ctx, phrase)).date_from == expected


@pytest.mark.parametrize(
    ("phrase", "expected", "part"),
    [
        # Spanish: 3 of the 73 published cases.
        ("mañana", date(2026, 9, 19), None),
        ("pasado mañana", date(2026, 9, 21), None),
        ("dentro de una semana", date(2026, 9, 25), None),
        ("dentro de quince días", date(2026, 10, 2), None),
        ("el sábado por la mañana", date(2026, 9, 19), "morning"),
        ("el martes por la tarde", date(2026, 9, 22), "afternoon"),
        ("el jueves que viene", date(2026, 9, 24), None),
        ("a primera hora del lunes doce de octubre", date(2026, 10, 13), "morning"),
        # Catalan: 1 of the 73.
        ("demà", date(2026, 9, 19), None),
        ("demà passat", date(2026, 9, 21), None),
        ("dissabte al matí", date(2026, 9, 19), "morning"),
        ("dijous a la tarda", date(2026, 9, 24), "afternoon"),
    ],
)
async def test_the_vocabulary_is_not_english_only(
    ctx: ToolContext, phrase: str, expected: date, part: str | None
) -> None:
    window = await _window(ctx, phrase)
    assert window.rejection is None, phrase
    assert window.date_from == expected
    if part == "morning":
        assert window.time_to == time(14, 0)
    elif part == "afternoon":
        assert window.time_from == time(14, 0)


async def test_a_closed_day_moves_and_says_so(ctx: ToolContext) -> None:
    """Fiesta Nacional shuts the network. The caller takes the next open day."""
    window = await _window(ctx, "first thing on Monday the twelfth of October")
    assert window.date_from == date(2026, 10, 13)
    assert window.moved_from_closed_day is True
    assert window.time_to == time(14, 0)  # still first thing


async def test_an_open_day_is_never_flagged_as_moved(ctx: ToolContext) -> None:
    assert (await _window(ctx, "this coming Monday")).moved_from_closed_day is False


async def test_nothing_is_booked_on_the_day_of_the_call(ctx: ToolContext) -> None:
    window = await _window(ctx, "today")
    assert window.date_from == date(2026, 9, 19)
    assert window.moved_from_closed_day is True  # not the day that was asked for


async def test_morning_ends_where_afternoon_begins(ctx: ToolContext) -> None:
    morning = await _window(ctx, "tomorrow", "morning")
    afternoon = await _window(ctx, "tomorrow", "afternoon")
    assert morning.time_to == time(14, 0) == afternoon.time_from


async def test_the_earliest_asks_for_a_window_not_a_day(ctx: ToolContext) -> None:
    window = await _window(ctx, "as soon as possible")
    assert window.date_from == date(2026, 9, 19)
    assert window.date_to > window.date_from
    assert window.moved_from_closed_day is False  # no day was asked for


@pytest.mark.parametrize("phrase", ["last Monday", "the thirty-second of October", "whichever"])
async def test_a_phrase_outside_the_vocabulary_returns_a_typed_reason(
    ctx: ToolContext, phrase: str
) -> None:
    window = await _window(ctx, phrase)
    assert window.rejection is not None
    assert window.rejection.reason == "out_of_scope"


# ---- find_slots ----------------------------------------------------------


async def test_todays_slots_are_never_offered(ctx: ToolContext) -> None:
    """/availability lists today's free slots. None of them is bookable."""
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            specialty_id="general_practice",
            date_from=date(2026, 9, 18),
            date_to=date(2026, 9, 21),
        ),
    )
    assert answer.slots
    assert all(s.start.astimezone(MADRID).date() > NOW.date() for s in answer.slots)


async def test_a_morning_window_stops_before_14(ctx: ToolContext) -> None:
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            specialty_id="general_practice",
            date_from=date(2026, 9, 21),
            date_to=date(2026, 9, 21),
            time_to=time(14, 0),
        ),
    )
    assert answer.slots
    assert all(s.start.astimezone(MADRID).time() < time(14, 0) for s in answer.slots)


async def test_a_window_longer_than_the_api_allows_is_split(ctx: ToolContext) -> None:
    """A span over 14 days is a 422. The window is walked, not truncated."""
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            specialty_id="general_practice",
            date_from=date(2026, 9, 21),
            date_to=date(2026, 10, 16),
        ),
    )
    assert answer.rejection is None
    days = {s.start.astimezone(MADRID).date() for s in answer.slots}
    assert max(days) > date(2026, 10, 5)  # the far end of the window was reached too


async def test_shut_is_not_the_same_as_full(ctx: ToolContext) -> None:
    """Sunday: every site is closed. That is clinic_closed, and nobody is blocked."""
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            specialty_id="general_practice",
            date_from=date(2026, 9, 20),
            date_to=date(2026, 9, 20),
        ),
    )
    assert answer.slots == []
    assert answer.blocked == []  # a provider on leave is not why the caller got nothing
    assert answer.rejection is not None
    assert answer.rejection.reason == "clinic_closed"


async def test_a_blocked_provider_survives_an_open_window(ctx: ToolContext) -> None:
    """Dr. Requena is on leave all event. On an open day that rule is the answer."""
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            specialty_id="general_practice",
            date_from=date(2026, 9, 21),
            date_to=date(2026, 9, 25),
        ),
    )
    assert [b.provider_id for b in answer.blocked] == ["PR07"]
    assert answer.blocked[0].reason == "provider_on_leave"
    assert answer.rejection is None  # slots exist; the rule is not a refusal


async def test_a_site_closed_that_afternoon_simply_has_nothing(ctx: ToolContext) -> None:
    """Sur shuts Friday lunchtime: a Friday afternoon there is empty, not blocked."""
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            location_id="sur",
            specialty_id="orthopaedics",
            date_from=date(2026, 9, 25),
            date_to=date(2026, 9, 25),
            time_from=time(14, 0),
        ),
    )
    assert answer.slots == []
    assert answer.rejection is not None
    assert answer.rejection.reason == "no_availability"  # the site opened that morning


# ---- widen_days: problem 7, no slot free -----------------------------------


async def test_widen_days_finds_the_nearest_alternative(ctx: ToolContext) -> None:
    """The same empty Friday afternoon at Sur, but now free to look further out."""
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            location_id="sur",
            specialty_id="orthopaedics",
            date_from=date(2026, 9, 25),
            date_to=date(2026, 9, 25),
            time_from=time(14, 0),
            widen_days=7,
        ),
    )
    assert answer.widened is True
    assert answer.rejection is None
    assert answer.slots  # a weekday afternoon further out is open
    assert all(s.location_id == "sur" for s in answer.slots)
    assert all(s.start.astimezone(MADRID).time() >= time(14, 0) for s in answer.slots)


async def test_widen_days_still_says_no_availability_when_it_truly_isnt_there(
    ctx: ToolContext,
) -> None:
    """No site is open past 20:00. Widening further out cannot invent a slot.

    Dermatology (one provider, never on leave) keeps this a pure no_availability
    case: nothing here comes from a blocked provider surviving the window.
    """
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            specialty_id="dermatology",
            date_from=date(2026, 9, 21),
            date_to=date(2026, 9, 25),
            time_from=time(21, 0),
            widen_days=30,
        ),
    )
    assert answer.widened is True
    assert answer.slots == []
    assert answer.rejection is not None
    assert answer.rejection.reason == "no_availability"


async def test_widen_days_is_never_reached_for_a_real_rule_or_a_closure(
    ctx: ToolContext,
) -> None:
    """Sunday is clinic_closed, not no_availability: widen_days must not fire on it."""
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            specialty_id="general_practice",
            date_from=date(2026, 9, 20),
            date_to=date(2026, 9, 20),
            widen_days=14,
        ),
    )
    assert answer.widened is False
    assert answer.rejection is not None
    assert answer.rejection.reason == "clinic_closed"


# ---- language filter: problem 11 -------------------------------------------


async def test_language_filter_is_empty_rather_than_inventing_a_speaker(
    ctx: ToolContext,
) -> None:
    """The fixtures' one dermatologist speaks Spanish and English, never Catalan."""
    answer = await find_slots(
        ctx,
        FindSlotsInput(
            specialty_id="dermatology",
            date_from=date(2026, 9, 21),
            date_to=date(2026, 10, 2),
            language="ca",
        ),
    )
    assert answer.slots == []


# ---- list_appointments and the prepare_* guards --------------------------


async def test_upcoming_is_split_against_the_call_not_the_machine(ctx: ToolContext) -> None:
    upcoming = await list_appointments(ctx, ListAppointmentsInput(patient_id=PATIENT))
    past = await list_appointments(ctx, ListAppointmentsInput(patient_id=PATIENT, when="past"))
    assert [a.appointment_id for a in upcoming.appointments] == ["A0001"]
    assert {a.appointment_id for a in past.appointments} == {"A9001", "A9002"}
    assert all(a.start > ctx.now for a in upcoming.appointments)
    assert all(a.start <= ctx.now for a in past.appointments)


async def test_a_past_visit_cannot_be_cancelled(ctx: ToolContext) -> None:
    result = await prepare_cancel(
        ctx, PrepareCancelInput(appointment_id="A9001", patient_id=PATIENT)
    )
    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "out_of_scope"


async def test_another_patients_appointment_is_not_the_callers_to_cancel(ctx: ToolContext) -> None:
    result = await prepare_cancel(
        ctx, PrepareCancelInput(appointment_id="A0002", patient_id=PATIENT)
    )
    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "caller_not_authorised"


async def test_an_invented_appointment_id_is_never_submitted(ctx: ToolContext) -> None:
    result = await prepare_cancel(
        ctx, PrepareCancelInput(appointment_id="A1234", patient_id=PATIENT)
    )
    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "out_of_scope"


async def test_the_childs_appointment_is_cancelled_under_the_childs_id(ctx: ToolContext) -> None:
    result = await prepare_cancel(ctx, PrepareCancelInput(appointment_id="A0002", patient_id=CHILD))
    assert result.rejection is None
    assert result.action is not None
    assert result.action.appointment_id == "A0002"


async def test_two_cancellations_in_one_call_do_not_cross_contaminate(
    ctx: ToolContext,
) -> None:
    """Problem 8: cancelling for two different patients in the same call, in turn."""
    first = await prepare_cancel(
        ctx, PrepareCancelInput(appointment_id="A0001", patient_id=PATIENT)
    )
    second = await prepare_cancel(
        ctx, PrepareCancelInput(appointment_id="A0002", patient_id=CHILD)
    )
    assert first.rejection is None
    assert first.action is not None
    assert first.action.appointment_id == "A0001"
    assert second.rejection is None
    assert second.action is not None
    assert second.action.appointment_id == "A0002"
    # Neither cancellation borrowed the other patient's authorisation.
    cross = await prepare_cancel(ctx, PrepareCancelInput(appointment_id="A0001", patient_id=CHILD))
    assert cross.rejection is not None
    assert cross.rejection.reason == "caller_not_authorised"


async def test_a_past_visit_cannot_be_moved(ctx: ToolContext) -> None:
    result = await prepare_reschedule(
        ctx,
        PrepareRescheduleInput(
            appointment_id="A9002",
            slot=Slot(
                start=datetime(2026, 9, 23, 16, 30, tzinfo=MADRID),
                provider_id="PR01",
                location_id="centro",
                appointment_type_id="review",
            ),
            policy_id="sanitas",
        ),
    )
    assert result.action is None
    assert result.rejection is not None


async def test_a_move_keeps_the_id_from_the_api_and_the_new_slots_ids(ctx: ToolContext) -> None:
    slot = Slot(
        start=datetime(2026, 9, 23, 16, 30, tzinfo=MADRID),
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
    )
    result = await prepare_reschedule(
        ctx,
        PrepareRescheduleInput(appointment_id="A0001", slot=slot, policy_id="sanitas"),
    )
    assert result.rejection is None
    assert result.action is not None
    assert result.action.appointment_id == "A0001"
    assert result.action.provider_id == "PR01"
    assert result.action.location_id == "centro"
    assert result.action.slot == slot.start


async def test_a_closure_day_is_not_a_slot_to_move_to(ctx: ToolContext) -> None:
    result = await prepare_reschedule(
        ctx,
        PrepareRescheduleInput(
            appointment_id="A0001",
            slot=Slot(
                start=datetime(2026, 10, 12, 10, 15, tzinfo=MADRID),
                provider_id="PR01",
                location_id="centro",
                appointment_type_id="review",
            ),
            policy_id="sanitas",
        ),
    )
    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "clinic_closed"
