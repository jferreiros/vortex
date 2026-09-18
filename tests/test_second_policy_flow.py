"""Problem 17 (the second policy): the plumbing already exists on
``check_eligibility``/``find_slots``/``prepare_booking`` — an ``insurer``
named on the call overrides the patient's own record at every step. What was
missing was a fixture built for exactly this and a proof of the whole chain
landing the *second* plan's id on the submitted action, never the first's.

Elena (``P00250``) is on ASISA only on file. ASISA is the one plan that never
covers Arenal Sur, the physiotherapist's only site — so asking for
physiotherapy there is refused on ``location_not_covered`` until she names
Sanitas, which the API has no record of at all.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from vortex.clinic.client import FakeClinicClient
from vortex.contract import (
    MADRID,
    CheckEligibilityInput,
    FindSlotsInput,
    PrepareBookingInput,
    ToolContext,
)
from vortex.diary.tools import find_slots, prepare_booking
from vortex.line.submit import DryRunSubmitClient
from vortex.observability.calllog import CallLog
from vortex.rules.tools import INSURANCE_REASONS, check_eligibility

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)
ELENA = "P00250"
CONTROL_PATIENT = "P00042"


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        call_id="CA-second-policy",
        now=NOW,
        from_number="+34677111222",  # Elena's own line
        clinic=FakeClinicClient(),
        log=CallLog("CA-second-policy", tmp_path / "calls.jsonl"),
        submitter=DryRunSubmitClient(),
    )


async def test_asisa_alone_is_refused_for_physiotherapy_at_sur(ctx: ToolContext) -> None:
    verdict = await check_eligibility(
        ctx,
        CheckEligibilityInput(
            patient_id=ELENA, specialty_id="physiotherapy", location_id="sur"
        ),
    )
    assert verdict.allowed is False
    assert verdict.rejection is not None
    assert verdict.rejection.reason in INSURANCE_REASONS
    assert verdict.rejection.reason == "location_not_covered"


async def test_naming_sanitas_unlocks_it(ctx: ToolContext) -> None:
    verdict = await check_eligibility(
        ctx,
        CheckEligibilityInput(
            patient_id=ELENA, specialty_id="physiotherapy", location_id="sur", insurer="sanitas"
        ),
    )
    assert verdict.allowed is True
    assert verdict.rejection is None


async def test_the_whole_chain_books_under_the_second_plan_not_the_first(
    ctx: ToolContext,
) -> None:
    verdict = await check_eligibility(
        ctx,
        CheckEligibilityInput(
            patient_id=ELENA, specialty_id="physiotherapy", location_id="sur", insurer="sanitas"
        ),
    )
    assert verdict.allowed is True

    availability = await find_slots(
        ctx,
        FindSlotsInput(
            patient_id=ELENA,
            specialty_id="physiotherapy",
            location_id="sur",
            insurer="sanitas",
            date_from=date(2026, 9, 21),
            date_to=date(2026, 10, 2),
        ),
    )
    assert availability.slots, "Sanitas covers Sur: something must be offered"

    booking = await prepare_booking(
        ctx,
        PrepareBookingInput(patient_id=ELENA, slot=availability.slots[0], policy_id="sanitas"),
    )
    assert booking.rejection is None
    assert booking.action is not None
    assert booking.action.policy_id == "sanitas"
    assert booking.action.policy_id != "asisa"  # never the plan on file


async def test_control_case_the_own_plan_already_works(ctx: ToolContext) -> None:
    """Marta's own Sanitas covers this. A second policy must never be invented."""
    control_ctx = ToolContext(
        call_id="CA-control",
        now=NOW,
        from_number="+34612345678",
        clinic=FakeClinicClient(),
        log=CallLog("CA-control", ctx.log.path.parent / "control.jsonl"),
        submitter=DryRunSubmitClient(),
    )
    verdict = await check_eligibility(
        control_ctx,
        CheckEligibilityInput(patient_id=CONTROL_PATIENT, specialty_id="general_practice"),
    )
    assert verdict.allowed is True
    assert verdict.rejection is None
