"""The 19 Sep clinic-day mix: volume, refusals with reasons, few escalations."""

from __future__ import annotations

from datetime import datetime

from evals.corpus.clinic_day import (
    DAY,
    N_CALLS,
    N_ESCALATE,
    N_REGISTER,
    N_REJECT,
    build_clinic_day_events,
    mix_from_events,
)
from vortex.contract import MADRID


def test_clinic_day_mix_matches_marta() -> None:
    stats = mix_from_events(build_clinic_day_events())
    assert stats["calls"] == N_CALLS
    assert stats["calls"] > 47
    assert 15 <= stats["unresolved_pct"] <= 20
    assert stats["escalated_share_of_unresolved_pct"] <= 10
    assert stats["escalated"] == N_ESCALATE
    assert stats["rejected"] == N_REJECT
    assert stats["new_patients"] == N_REGISTER
    assert set(stats["reasons"])


def test_every_refusal_carries_a_typed_reason() -> None:
    events = build_clinic_day_events()
    refusals = [
        action
        for event in events
        if event.get("kind") == "call.summary"
        for action in (event.get("actions") or [])
        if action.get("action") == "NO_ACTION"
    ]
    assert len(refusals) == N_REJECT
    assert all(action.get("reason") for action in refusals)


def test_escalations_are_medical_emergency() -> None:
    events = build_clinic_day_events()
    escalations = [
        action
        for event in events
        if event.get("kind") == "call.summary"
        for action in (event.get("actions") or [])
        if action.get("action") == "ESCALATE"
    ]
    assert len(escalations) == N_ESCALATE
    assert all(action.get("reason") == "medical_emergency" for action in escalations)


def test_register_calls_are_new_patients() -> None:
    events = build_clinic_day_events()
    registers = [
        action
        for event in events
        if event.get("kind") == "call.summary"
        for action in (event.get("actions") or [])
        if action.get("action") == "REGISTER"
    ]
    assert len(registers) == N_REGISTER
    nids = {action["new_patient"]["national_id"] for action in registers}
    assert len(nids) == N_REGISTER
    for action in registers:
        patient = action["new_patient"]
        assert patient["given_name"]
        assert patient["email"]
        assert patient["insurer"]


def test_every_call_is_today() -> None:
    for event in build_clinic_day_events():
        if event.get("kind") != "call.started":
            continue
        stamp = datetime.fromisoformat(str(event["ts"])).astimezone(MADRID)
        assert stamp.date() == DAY
