"""diary.prepare_booking: the BookAction copies the availability slot's ids
verbatim, and a slot the clinic is not offering is rejected, never booked."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from vortex.clinic.client import FakeClinicClient
from vortex.contract import MADRID, PrepareBookingInput, Slot, ToolContext
from vortex.diary.tools import prepare_booking
from vortex.line.submit import DryRunSubmitClient
from vortex.observability.calllog import CallLog

NOW = datetime(2026, 9, 18, 10, 30, tzinfo=MADRID)  # a Friday
PATIENT = "P00042"  # has_visited_before -> review type
POLICY = "sanitas"


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        call_id="CA-test",
        now=NOW,
        from_number="+34612345678",
        clinic=FakeClinicClient(),
        log=CallLog("CA-test", tmp_path / "calls.jsonl"),
        submitter=DryRunSubmitClient(),
    )


async def _offered_slot(ctx: ToolContext, day) -> Slot:
    answer = await ctx.clinic.availability(date_from=day, date_to=day, patient_id=PATIENT)
    assert answer.slots, f"fake clinic offers nothing on {day}"
    return answer.slots[0]


async def test_action_copies_the_offered_slot_verbatim(ctx: ToolContext) -> None:
    day = (NOW + timedelta(days=1)).date()  # Saturday: only Centro opens
    slot = await _offered_slot(ctx, day)

    result = await prepare_booking(
        ctx,
        PrepareBookingInput(
            patient_id=PATIENT,
            slot=slot,
            policy_id=POLICY,
        ),
    )

    assert result.rejection is None
    action = result.action
    assert action is not None
    assert action.patient_id == PATIENT
    assert action.provider_id == slot.provider_id
    assert action.location_id == slot.location_id
    assert action.appointment_type_id == slot.appointment_type_id
    assert action.slot == slot.start
    assert action.policy_id == POLICY


async def test_same_day_slot_is_rejected(ctx: ToolContext) -> None:
    slot = Slot(
        start=NOW + timedelta(hours=2),
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
    )
    result = await prepare_booking(
        ctx,
        PrepareBookingInput(
            patient_id=PATIENT,
            slot=slot,
            policy_id=POLICY,
        ),
    )
    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "no_availability"


async def test_slot_outside_the_bookable_window_is_rejected(ctx: ToolContext) -> None:
    slot = Slot(
        start=datetime(2026, 12, 1, 10, 0, tzinfo=MADRID),
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
    )
    result = await prepare_booking(
        ctx,
        PrepareBookingInput(
            patient_id=PATIENT,
            slot=slot,
            policy_id=POLICY,
        ),
    )
    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "no_availability"


async def test_closure_day_is_rejected(ctx: ToolContext) -> None:
    slot = Slot(
        start=datetime(2026, 10, 12, 10, 0, tzinfo=MADRID),  # Monday 12 Oct: closed
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
    )
    result = await prepare_booking(
        ctx,
        PrepareBookingInput(
            patient_id=PATIENT,
            slot=slot,
            policy_id=POLICY,
        ),
    )
    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "clinic_closed"


async def test_slot_the_clinic_is_not_offering_is_rejected(ctx: ToolContext) -> None:
    day = (NOW + timedelta(days=1)).date()
    offered = await _offered_slot(ctx, day)
    invented = Slot(
        start=offered.start + timedelta(minutes=5),  # not a real 15-minute slot
        provider_id=offered.provider_id,
        location_id=offered.location_id,
        appointment_type_id=offered.appointment_type_id,
    )
    result = await prepare_booking(
        ctx,
        PrepareBookingInput(
            patient_id=PATIENT,
            slot=invented,
            policy_id=POLICY,
        ),
    )
    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "no_availability"


async def test_wrong_type_id_on_a_real_slot_is_rejected(ctx: ToolContext) -> None:
    day = (NOW + timedelta(days=1)).date()
    offered = await _offered_slot(ctx, day)
    wrong_type = Slot(
        start=offered.start,
        provider_id=offered.provider_id,
        location_id=offered.location_id,
        appointment_type_id="first_visit",  # P00042 has visited before -> review
    )
    result = await prepare_booking(
        ctx,
        PrepareBookingInput(
            patient_id=PATIENT,
            slot=wrong_type,
            policy_id=POLICY,
        ),
    )
    assert result.action is None
    assert result.rejection is not None
