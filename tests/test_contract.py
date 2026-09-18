"""The contract holds: every tool has a stub that returns its declared output,
every action serialises to the route's snake_case body, and the reason
vocabulary is exactly the contract's eighteen values.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import get_args

import pytest

from vortex import contract, tools
from vortex.clinic.client import FakeClinicClient
from vortex.contract import MADRID, BookAction, NoAction, RegisterAction, ToolContext
from vortex.line.submit import DryRunSubmitClient
from vortex.observability.calllog import CallLog

NOW = datetime(2026, 9, 18, 10, 30, tzinfo=MADRID)


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


def test_reason_vocabulary_is_closed() -> None:
    assert len(contract.RULE_REASONS) == 11
    assert len(contract.OTHER_REASONS) == 7
    assert set(get_args(contract.DeclineReason)) == set(contract.ALL_REASONS)


def test_every_rule_reason_has_a_way_to_be_reported() -> None:
    for reason in contract.RULE_REASONS:
        NoAction(reason=reason)  # validates against the Literal


def test_action_payloads_match_the_routes() -> None:
    book = BookAction(
        patient_id="P00042",
        provider_id="PR05",
        location_id="sur",
        appointment_type_id="review",
        slot=datetime(2026, 9, 24, 16, 30, tzinfo=MADRID),
        policy_id="sanitas",
    )
    assert contract.action_route(book) == "/api/v1/submit/book"
    payload = contract.action_payload(book, "3fa85f64")
    assert payload == {
        "call_id": "3fa85f64",
        "patient_id": "P00042",
        "provider_id": "PR05",
        "location_id": "sur",
        "appointment_type_id": "review",
        "slot": "2026-09-24T16:30:00+02:00",
        "policy_id": "sanitas",
    }
    register = RegisterAction(
        given_name="Ana",
        first_surname="García",
        second_surname="Pérez",
        national_id="12345678Z",
        date_of_birth=date(1990, 1, 2),
        phone="+34600000000",
        email="ana.garcia@gmail.com",
        insurer="adeslas",
    )
    body = contract.action_payload(register, "x")
    assert body["date_of_birth"] == "1990-01-02"
    assert "kind" not in body


SAMPLE_ARGS: dict[str, dict] = {
    "find_patient": {"name": "Marta Ruiz"},
    "validate_national_id": {"value": "12345678z"},
    "build_registration": {
        "given_name": "Ana",
        "first_surname": "García",
        "second_surname": "Pérez",
        "national_id": "12345678Z",
        "date_of_birth": "1990-01-02",
        "phone": "+34600000000",
        "email": "ana@example.com",
        "insurer": "adeslas",
    },
    "resolve_date": {"phrase": "next Thursday", "part_of_day": "morning"},
    "find_slots": {
        "specialty_id": "general_practice",
        "date_from": "2026-09-21",
        "date_to": "2026-09-25",
    },
    "list_appointments": {"patient_id": "P00042"},
    "prepare_booking": {
        "patient_id": "P00042",
        "slot": {
            "start": "2026-09-21T10:15:00+02:00",
            "provider_id": "PR01",
            "location_id": "centro",
            "appointment_type_id": "review",
        },
        "policy_id": "sanitas",
    },
    "prepare_reschedule": {
        "appointment_id": "A0001",
        "slot": {
            "start": "2026-09-21T10:15:00+02:00",
            "provider_id": "PR01",
            "location_id": "centro",
            "appointment_type_id": "review",
        },
        "policy_id": "sanitas",
    },
    "prepare_cancel": {"appointment_id": "A0001", "patient_id": "P00042"},
    "check_eligibility": {"patient_id": "P00042", "specialty_id": "dermatology"},
    "triage": {"complaint": "went over on my ankle"},
    "nearest_location": {"address": "Calle de Madrid 54, Getafe", "specialty_id": "orthopaedics"},
    "find_provider": {"spoken_name": "Sáez"},
    "clinic_facts": {"weekday": "saturday"},
    "submit_action": {"action": {"kind": "no-action", "reason": "out_of_scope"}},
}


@pytest.mark.parametrize("name", sorted(tools.TOOLS))
async def test_every_tool_returns_its_declared_output(name: str, ctx: ToolContext) -> None:
    assert name in SAMPLE_ARGS, f"add sample args for {name}"
    result = await tools.call_tool(name, ctx, SAMPLE_ARGS[name])
    assert isinstance(result, tools.TOOLS[name].output_model)
    result.model_dump(mode="json")  # JSON-safe for the model and the log


def test_function_schemas_cover_every_tool() -> None:
    schemas = tools.function_schemas()
    assert {s["name"] for s in schemas} == set(tools.TOOLS)
    for s in schemas:
        assert s["parameters"]["type"] == "object"


async def test_fake_clinic_answers_like_the_docs_say() -> None:
    clinic = FakeClinicClient()
    # phone folds to nine national digits, and the line belongs to the mother
    hits = await clinic.directory(phone="612345678")
    assert {p.patient_id for p in hits} == {"P00042", "P00107"}
    # exact fields filter: same name, split by date of birth
    both = await clinic.directory(name="Marta Ruiz")
    assert len(both) == 2
    one = await clinic.directory(name="Marta Ruiz", date_of_birth=date(1985, 3, 12))
    assert [p.patient_id for p in one] == ["P00042"]
    # availability names the type and the blocked provider
    avail = await clinic.availability(
        date_from=date(2026, 9, 21), date_to=date(2026, 9, 25), specialty_id="general_practice"
    )
    assert avail.appointment_type is not None
    assert any(b.provider_id == "PR07" and b.reason == "provider_on_leave" for b in avail.blocked)
    assert all(
        s.appointment_type_id == avail.appointment_type.appointment_type_id for s in avail.slots
    )
    # upcoming appointments are the only source of an appointment_id
    upcoming = await clinic.appointments("P00042")
    assert [a.appointment_id for a in upcoming] == ["A0001"]
