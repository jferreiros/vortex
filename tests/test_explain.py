from __future__ import annotations

from vortex.contract import ALL_REASONS
from vortex.observability.explain import (
    REASON_TEXT,
    outcome_text,
    outcome_title,
    payload_rows,
    stage_of,
    stats_for,
    step_text,
)
from vortex.observability.view import CallCard, ToolStep, Turn


def _booked() -> CallCard:
    card = CallCard(call_id="CA-1", ended=True, duration_ms=42000)
    card.turns = [Turn("assistant", "Hola"), Turn("user", "Cita")]
    card.tools = [
        ToolStep("find_patient", status="ok", ms=40.0, result={"status": "found", "patient": {}}),
        ToolStep("find_slots", status="ok", ms=50.0, result={"slots": [{"start": "x"}]}),
    ]
    card.action_kind = "book"
    card.action_payload = {"call_id": "CA-1", "slot": "x", "patient_id": "P1"}
    card.submit_status = "accepted"
    card.patient_name = "Marta Ruiz"
    card.provider_name = "Dra. Ortiz"
    card.slot = "19/09 10:15"
    return card


def test_every_contract_reason_has_a_sentence() -> None:
    missing = [r for r in ALL_REASONS if r not in REASON_TEXT]
    assert not missing


def test_stage_progresses_with_evidence() -> None:
    assert stage_of(None) == 0
    card = CallCard(call_id="x")
    assert stage_of(card) == 0
    card.turns.append(Turn("user", "hi"))
    assert stage_of(card) == 1
    card.tools.append(ToolStep("find_patient"))
    assert stage_of(card) == 2
    card.tools.append(ToolStep("find_slots"))
    assert stage_of(card) == 3
    card.submit_status = "accepted"
    assert stage_of(card) == 4


def test_outcome_sentences() -> None:
    card = _booked()
    assert outcome_title(card) == "Booked"
    assert "Marta Ruiz" in outcome_text(card)
    assert "Dra. Ortiz" in outcome_text(card)
    refused = CallCard(call_id="r", ended=True, action_kind="no-action")
    refused.decline_reason = "specialty_not_covered"
    assert outcome_title(refused) == "No action"
    assert "insurance" in outcome_text(refused)
    assert outcome_title(None) == "Waiting for a call"


def test_step_text_reads_results() -> None:
    step = ToolStep(
        "check_eligibility",
        status="ok",
        result={"allowed": False, "rejection": {"reason": "referral_required", "detail": "d"}},
    )
    assert step_text(step) == "Rejected: referral_required — d"
    assert step_text(ToolStep("find_slots", status="ok", result={"slots": []})).startswith(
        "No slot"
    )
    assert step_text(ToolStep("x", status="fail", error="boom")) == "Failed: boom"


def test_stats_and_payload_rows() -> None:
    card = _booked()
    live = CallCard(call_id="live")
    live.turns.append(Turn("user", "..."))
    stats = stats_for([card, live])
    assert stats.calls == 2
    assert stats.live == 1
    assert stats.booked == 1
    assert stats.submitted == 1
    assert stats.submit_rate == 1.0
    assert stats.median_duration_s == 42.0
    assert stats.median_tool_ms == 45.0
    rows = payload_rows(card)
    assert rows[0][0] == "patient_id"
    assert all(k != "call_id" for k, _ in rows)
