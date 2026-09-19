from __future__ import annotations

from datetime import datetime

from vortex.contract import BookAction, EscalateAction, MADRID, NoAction
from vortex.jev.policy import decide

SLOT = datetime(2026, 9, 24, 11, 0, tzinfo=MADRID)
BOOK = BookAction(
    patient_id="P00001",
    provider_id="PR01",
    location_id="centro",
    appointment_type_id="review",
    slot=SLOT,
    policy_id="mapfre",
)


def test_a_high_red_flag_escalates_a_booking() -> None:
    out = decide(BOOK, red_flag=0.97, out_of_scope=0.1)
    assert isinstance(out, EscalateAction)
    assert out.reason == "medical_emergency"


def test_a_booking_survives_a_mid_out_of_scope_score() -> None:
    out = decide(BOOK, red_flag=0.1, out_of_scope=0.66)
    assert out == BOOK


def test_a_very_high_out_of_scope_vetoes_a_booking() -> None:
    out = decide(BOOK, red_flag=0.05, out_of_scope=0.93)
    assert isinstance(out, NoAction)
    assert out.reason == "out_of_scope"


def test_an_existing_escalate_is_left_alone() -> None:
    action = EscalateAction(reason="medical_emergency")
    assert decide(action, red_flag=0.2, out_of_scope=0.9) == action


def test_a_default_refusal_becomes_out_of_scope_when_jev_is_sure() -> None:
    action = NoAction(reason="patient_not_found")
    out = decide(action, red_flag=0.1, out_of_scope=0.84)
    assert isinstance(out, NoAction)
    assert out.reason == "out_of_scope"
