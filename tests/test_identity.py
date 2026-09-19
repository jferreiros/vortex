"""identity/: the directory, the DNI/NIE check letter, and who is on the line.

The eval harness (``evals/logic/cases/identity.yaml``) covers the published
matching and near-miss vocabulary case by case. This file covers what the
harness does not: the pure check-letter arithmetic, and the structural signal
behind problem 9 — booking for someone other than whoever first identified
the line, which is legitimate and must never be blocked, only made visible.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import vortex.clinic_policy as clinic_policy
from vortex.clinic.client import FakeClinicClient
from vortex.contract import (
    MADRID,
    BuildRegistrationInput,
    FindPatientInput,
    PrepareBookingInput,
    PrepareCancelInput,
    Slot,
    ToolContext,
)
from vortex.identity.dictation import check_email, check_phone
from vortex.identity.tools import (
    build_registration,
    check_national_id,
    find_patient,
    normalize_email,
    normalize_phone,
)
from vortex.line.submit import DryRunSubmitClient
from vortex.observability.calllog import CallLog
from vortex.tools import call_tool

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)
MOTHER = "P00042"
CHILD = "P00107"


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        call_id="CA-identity",
        now=NOW,
        from_number="+34612345678",  # the mother's line
        clinic=FakeClinicClient(),
        log=CallLog("CA-identity", tmp_path / "calls.jsonl"),
        submitter=DryRunSubmitClient(),
    )


def logged(ctx: ToolContext) -> list[dict]:
    if not ctx.log.path.exists():
        return []
    return [json.loads(line) for line in ctx.log.path.read_text().splitlines() if line.strip()]


# ---- dictated email / phone (problem 4; docs/research/05 §3) ---------------


@pytest.mark.parametrize(
    ("spoken", "address"),
    [
        ("ana punto garcia arroba gmail punto com", "ana.garcia@gmail.com"),  # es
        ("ana punt garcia arrova gmail punt com", "ana.garcia@gmail.com"),  # ca
        ("ana dot garcia at gmail dot com", "ana.garcia@gmail.com"),  # en
        ("sergio guion bajo martinez arroba outlook punto es", "sergio_martinez@outlook.es"),
        ("natalia dot munoz 86 at hotmail dot com", "natalia.munoz86@hotmail.com"),
        ("juan arroba yimeil punto com", "juan@gmail.com"),  # STT domain alias
        ("Ana.Garcia@Gmail.com", "ana.garcia@gmail.com"),  # already an address
    ],
)
def test_spoken_email_maps_and_validates_without_dns(spoken: str, address: str) -> None:
    result = check_email(spoken)
    assert result.normalized == address
    assert result.valid is True
    assert normalize_email(spoken) == address


@pytest.mark.parametrize(
    ("spoken", "e164"),
    [
        ("seis uno dos tres cuatro cinco seis siete ocho", "+34612345678"),  # es digits
        ("sis un dos tres quatre cinc sis set vuit", "+34612345678"),  # ca digits
        ("612 34 56 78", "+34612345678"),  # grouped digits
    ],
)
def test_spoken_phone_maps_through_phonenumbers_es(spoken: str, e164: str) -> None:
    result = check_phone(spoken)
    assert result.normalized == e164
    assert result.possible is True
    assert normalize_phone(spoken) == e164


def test_check_email_rejects_garbage_without_dns() -> None:
    result = check_email("esto no es un correo")
    assert result.valid is False
    assert "@" not in result.normalized


def test_organiser_7xx_mobile_is_possible_even_if_unallocated() -> None:
    """Platform fixtures use 7xx mobiles; is_valid_number would refuse them."""
    result = check_phone("792919982")
    assert result.normalized == "+34792919982"
    assert result.possible is True


# ---- check_national_id: DNI/NIE, mod-23 -----------------------------------


@pytest.mark.parametrize(
    ("value", "kind", "valid"),
    [
        ("12345678Z", "dni", True),  # Marta's own record
        ("12345678A", "dni", False),  # right digits, wrong letter
        ("X1234567L", "nie", True),  # Antonio's, X-prefixed
        ("Y1234567X", "nie", True),  # Y-prefixed, correct letter
        ("Y1234567Z", "nie", False),  # right digits, wrong letter
        ("not-an-id", "invalid", False),
    ],
)
def test_check_letter_arithmetic(value: str, kind: str, valid: bool) -> None:
    result = check_national_id(value)
    assert result.kind == kind
    assert result.valid is valid


def test_check_national_id_folds_spoken_separators() -> None:
    dictated = check_national_id("12 345 678-z")
    spelled = check_national_id("12345678Z")
    assert dictated.normalized == spelled.normalized
    assert dictated.valid is spelled.valid


def test_unique_one_edit_repair_is_a_digit_to_re_ask_not_a_valid_id() -> None:
    """seis/tres at one position fits Z, but only the caller says which digit they meant."""
    result = check_national_id("12645678Z")  # heard 6, 3 would fit the letter
    assert result.valid is False
    assert result.kind == "dni"
    assert result.normalized == "12645678Z"
    assert result.repaired_from is None
    assert result.ask_digit_positions == [2]


def test_unique_one_edit_repair_for_nie_is_not_valid_either() -> None:
    result = check_national_id("X1264567L")
    assert result.valid is False
    assert result.kind == "nie"
    assert result.normalized == "X1264567L"
    assert result.repaired_from is None
    assert result.ask_digit_positions == [2]


def test_ambiguous_one_edit_asks_for_the_differing_digits() -> None:
    result = check_national_id("12345778Z")
    assert result.valid is False
    assert result.normalized == "12345778Z"
    assert result.repaired_from is None
    assert result.ask_digit_positions == [0, 5, 7]


def test_wrong_letter_with_no_repair_stays_invalid() -> None:
    """Right digits, wrong letter, and no 1-edit yields that letter → still invalid."""
    result = check_national_id("12345678A")
    assert result.valid is False
    assert result.normalized == "12345678A"
    assert result.expected_letter == "Z"
    assert result.ask_digit_positions == []
    assert result.repaired_from is None


# ---- find_patient: ambiguity and near misses ------------------------------


async def test_a_name_shared_by_two_patients_is_ambiguous(ctx: ToolContext) -> None:
    result = await find_patient(ctx, FindPatientInput(name="Marta Ruiz"))
    assert result.status == "ambiguous"
    assert {p.patient_id for p in result.candidates} == {"P00042", "P00043"}
    assert result.ask_for  # a field that actually splits them, not a guess


async def test_a_wrong_digit_in_the_id_is_a_near_miss_not_a_match(ctx: ToolContext) -> None:
    result = await find_patient(
        ctx, FindPatientInput(name="Marta Ruiz López", national_id="12345679Z")
    )
    assert result.status == "not_found"
    assert any(p.patient_id == "P00042" for p in result.candidates)


async def test_a_repairable_misheard_id_is_never_searched_for_the_caller(
    ctx: ToolContext,
) -> None:
    """One confusion edit fits the letter; /directory still sees what the caller said."""
    result = await find_patient(
        ctx, FindPatientInput(name="Marta Ruiz López", national_id="12645678Z")
    )
    assert result.status == "not_found"
    assert result.patient is None
    assert any(p.patient_id == "P00042" for p in result.candidates)


async def test_a_line_shared_by_two_patients_is_still_ambiguous(ctx: ToolContext) -> None:
    """The mother's phone also rings for her son: the line alone never picks one."""
    result = await find_patient(ctx, FindPatientInput())
    assert result.status == "ambiguous"
    assert {p.patient_id for p in result.candidates} == {MOTHER, CHILD}


async def test_an_unshared_line_finds_its_own_owner(tmp_path: Path) -> None:
    solo = ToolContext(
        call_id="CA-identity-solo",
        now=NOW,
        from_number="+34699000111",  # P00043's own, unshared line
        clinic=FakeClinicClient(),
        log=CallLog("CA-identity-solo", tmp_path / "calls.jsonl"),
        submitter=DryRunSubmitClient(),
    )
    result = await find_patient(solo, FindPatientInput())
    assert result.status == "found"
    assert result.patient is not None
    assert result.patient.patient_id == "P00043"


async def test_clinic_settings_can_require_a_second_identifying_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clinic_policy, "identification_fields_required", lambda: 2)
    solo = ToolContext(
        call_id="CA-identity-lead",
        now=NOW,
        from_number="+34699000111",
        clinic=FakeClinicClient(),
        log=CallLog("CA-identity-lead", tmp_path / "calls.jsonl"),
        submitter=DryRunSubmitClient(),
    )
    by_line = await find_patient(solo, FindPatientInput())
    assert by_line.status == "ambiguous"
    by_two = await find_patient(
        solo,
        FindPatientInput(name="Marta Ruiz García", date_of_birth=date(1992, 11, 2)),
    )
    assert by_two.status == "found"


# ---- problem 9: caller identity vs. the patient actually booked -----------


async def _offered_slot(ctx: ToolContext, patient_id: str, specialty_id: str, day: date) -> Slot:
    answer = await ctx.clinic.availability(
        date_from=day, date_to=day, specialty_id=specialty_id, patient_id=patient_id
    )
    assert answer.slots, f"fake clinic offers nothing on {day} for {specialty_id}"
    return answer.slots[0]


async def test_booking_for_a_third_party_is_logged_not_blocked(ctx: ToolContext) -> None:
    """A mother identifies herself, then books for her son: legitimate, and traced."""
    caller = await find_patient(
        ctx, FindPatientInput(name="Marta Ruiz López", date_of_birth=date(1985, 3, 12))
    )
    assert caller.patient is not None and caller.patient.patient_id == MOTHER

    child = await find_patient(
        ctx, FindPatientInput(name="Lucas Ruiz López", date_of_birth=date(2018, 6, 20))
    )
    assert child.patient is not None and child.patient.patient_id == CHILD

    day = (NOW + timedelta(days=1)).date()  # Saturday: only Centro opens
    slot = await _offered_slot(ctx, CHILD, "paediatrics", day)
    booking = await call_tool(
        "prepare_booking",
        ctx,
        PrepareBookingInput(patient_id=CHILD, slot=slot, policy_id="sanitas").model_dump(
            mode="json"
        ),
    )
    assert booking.rejection is None

    events = [e for e in logged(ctx) if e["kind"] == "identity.third_party"]
    assert events, "a third-party booking must leave a trace"
    assert events[-1]["caller_patient_id"] == MOTHER
    assert events[-1]["target_patient_id"] == CHILD


async def test_booking_for_yourself_never_logs_a_third_party_event(ctx: ToolContext) -> None:
    """The control case: caller and target are the same patient, no event fires."""
    caller = await find_patient(
        ctx, FindPatientInput(name="Marta Ruiz López", date_of_birth=date(1985, 3, 12))
    )
    assert caller.patient is not None

    day = (NOW + timedelta(days=1)).date()  # Saturday: only Centro opens
    slot = await _offered_slot(ctx, MOTHER, "general_practice", day)
    booking = await call_tool(
        "prepare_booking",
        ctx,
        PrepareBookingInput(patient_id=MOTHER, slot=slot, policy_id="sanitas").model_dump(
            mode="json"
        ),
    )
    assert booking.rejection is None
    assert not [e for e in logged(ctx) if e["kind"] == "identity.third_party"]


async def test_a_third_party_cancellation_is_also_traced(ctx: ToolContext) -> None:
    caller = await find_patient(
        ctx, FindPatientInput(name="Marta Ruiz López", date_of_birth=date(1985, 3, 12))
    )
    assert caller.patient is not None and caller.patient.patient_id == MOTHER

    result = await call_tool(
        "prepare_cancel",
        ctx,
        PrepareCancelInput(appointment_id="A0002", patient_id=CHILD).model_dump(mode="json"),
    )
    assert result.rejection is None

    events = [e for e in logged(ctx) if e["kind"] == "identity.third_party"]
    assert events
    assert events[-1]["caller_patient_id"] == MOTHER
    assert events[-1]["target_patient_id"] == CHILD


# ---- registration: the phone is the line they dialled (problem 4) ----------
#
# The registration has eight fields and the call has three minutes. Fourteen
# registrations in one night ran to the wall clock at 170-209 s having asked for
# six of the eight, and every one of them ended on a refusal that scores nothing.
# The phone is the one field the call already holds before the caller speaks.


def a_registration(**overrides: object) -> BuildRegistrationInput:
    fields: dict[str, object] = {
        "given_name": "Isabel",
        "first_surname": "Hernández",
        "second_surname": "Ramos",
        "national_id": "11348757M",
        "date_of_birth": date(2005, 7, 15),
        "phone": "",
        "email": "isabel_hernandez32@outlook.es",
        "insurer": "sanitas",
    }
    fields.update(overrides)
    return BuildRegistrationInput(**fields)  # type: ignore[arg-type]


async def test_an_undictated_phone_comes_off_the_dialling_line(ctx: ToolContext) -> None:
    """The field we never have to ask for: Twilio handed it to us at connect."""
    result = await build_registration(ctx, a_registration())

    assert result.rejection is None
    assert result.action is not None
    assert result.action.phone == ctx.from_number


async def test_a_dropped_phone_key_is_not_a_failed_tool_call(ctx: ToolContext) -> None:
    """Told not to ask for it, a model drops the key rather than sending "". Same answer."""
    args = a_registration().model_dump(mode="json")
    del args["phone"]
    result = await call_tool("build_registration", ctx, args)

    assert result.rejection is None
    assert result.action is not None and result.action.phone == ctx.from_number


async def test_a_dictated_phone_still_wins_over_the_line(ctx: ToolContext) -> None:
    """Registering off a borrowed phone: what the caller said is their number."""
    result = await build_registration(ctx, a_registration(phone="699 111 222"))

    assert result.action is not None
    assert result.action.phone == "+34699111222"
    assert result.action.phone != ctx.from_number


async def test_no_caller_id_still_asks_for_the_phone(tmp_path: Path) -> None:
    """Nothing to fall back on. The rejection names the field, as it always did."""
    blind = ToolContext(
        call_id="CA-no-caller-id",
        now=NOW,
        from_number="",
        clinic=FakeClinicClient(),
        log=CallLog("CA-no-caller-id", tmp_path / "calls.jsonl"),
        submitter=DryRunSubmitClient(),
    )
    result = await build_registration(blind, a_registration())

    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.detail.startswith("phone:")


async def test_every_other_field_is_still_the_caller_s_to_dictate(ctx: ToolContext) -> None:
    """The phone default must not paper over a field nobody collected."""
    for field_name, blank in (
        ("given_name", ""),
        ("first_surname", ""),
        ("second_surname", ""),
        ("email", ""),
        ("insurer", ""),
    ):
        result = await build_registration(ctx, a_registration(**{field_name: blank}))
        assert result.action is None, field_name
        assert result.rejection is not None and result.rejection.detail.startswith(f"{field_name}:")


async def test_a_repairable_id_is_re_asked_never_registered(ctx: ToolContext) -> None:
    """A 1-edit reading fits the letter; the record still needs the digits from the caller."""
    result = await build_registration(ctx, a_registration(national_id="12645678Z"))

    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.detail.startswith("national_id:")
    assert "12345678Z" not in result.rejection.detail
    assert "position" in result.rejection.detail
