"""The rule engine's edges, where an eval case would only see the verdict.

The evals check what ``check_eligibility`` answers. These check the arithmetic
and the precedence behind it — the boundary the age rule turns on, and the
self-pay rule that stops a refusal being talked around.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from vortex.clinic.client import FakeClinicClient
from vortex.contract import MADRID, CheckEligibilityInput, FindPatientInput, ToolContext
from vortex.identity.tools import find_patient
from vortex.observability.calllog import CallLog
from vortex.rules import eligibility
from vortex.rules.tools import NO_RECORD_SKIPPED, check_eligibility


@pytest.fixture
def catalogue():
    return FakeClinicClient()._catalogue


@pytest.mark.parametrize(
    ("born", "on", "months"),
    [
        (date(2012, 9, 18), date(2026, 9, 17), 167),  # the day before the 14th birthday
        (date(2012, 9, 18), date(2026, 9, 18), 168),  # the 14th birthday itself
        (date(2012, 9, 18), date(2026, 9, 19), 168),
        (date(2026, 8, 20), date(2026, 9, 19), 0),  # a month short of one month
    ],
)
def test_age_in_months_counts_complete_months(born, on, months):
    assert eligibility.age_in_months(born, on) == months


def test_the_fourteenth_birthday_has_no_gap_and_no_overlap(catalogue):
    """Every age has exactly one specialty for a general complaint."""
    for months in (0, 100, 167, 168, 169, 900):
        found = eligibility.specialty_for_age(catalogue, months)
        assert found is not None, months
        assert found.specialty_id == ("paediatrics" if months < 168 else "general_practice")


def test_self_pay_is_not_a_fallback_for_someone_who_does_not_hold_it(catalogue):
    """Quoting ``privado`` at a refusal is inventing cover: the record's plan answers."""
    patient = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00043")
    plan = eligibility.resolve_plan(catalogue, patient, "privado")
    assert plan is not None
    assert plan.insurer_id == "adeslas"


def test_self_pay_is_honoured_when_the_record_says_so(catalogue):
    patient = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00043")
    patient = patient.model_copy(update={"insurer": "privado"})
    plan = eligibility.resolve_plan(catalogue, patient, "privado")
    assert plan is not None
    assert plan.insurer_id == "privado"


def test_a_second_policy_named_on_the_call_wins_over_the_record(catalogue):
    """Problem 17: the second plan is nowhere in the API. Naming it is the point."""
    patient = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00200")
    assert patient.insurer == "dkv"
    plan = eligibility.resolve_plan(catalogue, patient, "sanitas")
    assert plan is not None
    assert plan.insurer_id == "sanitas"


def test_a_plan_the_catalogue_does_not_know_is_not_a_refusal(catalogue):
    """A plan name we cannot place is not evidence of anything. It stands down."""
    patient = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00042")
    assert eligibility.resolve_plan(catalogue, patient, "a_plan_no_clinic_publishes") is None


def test_age_is_checked_before_insurance(catalogue):
    """An under-14 asking for general practice is an age refusal, whatever the plan.

    Both rules are true here; the reason submitted has to be the wider one, or
    the caller is told to change insurer when what they need is a paediatrician.
    """
    child = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00107")
    covers_nothing = next(
        p for p in catalogue.insurance_plans if p.insurer_id == "adeslas"
    ).model_copy(update={"specialty_ids": ["dermatology"]})
    verdict = eligibility.check_patient_rules(
        catalogue,
        child,
        specialty_id="general_practice",
        location_id=None,
        plan=covers_nothing,
        today=date(2026, 9, 18),
    )
    assert verdict is not None
    assert verdict.reason == "not_eligible_age"


def test_an_age_window_the_catalogue_does_not_publish_is_not_invented(catalogue):
    """Gynaecology carries no age limit, so the rules do not add one."""
    child = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00107")
    sanitas = next(p for p in catalogue.insurance_plans if p.insurer_id == "sanitas")
    verdict = eligibility.check_patient_rules(
        catalogue,
        child,
        specialty_id="gynaecology",
        location_id=None,
        plan=sanitas,
        today=date(2026, 9, 18),
    )
    assert verdict is None


def test_a_plan_that_covers_some_sites_only_refuses_when_none_of_them_serve(catalogue):
    """ASISA covers physio at Centro and Norte; the one physiotherapist is at Sur."""
    patient = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00042")
    asisa = next(p for p in catalogue.insurance_plans if p.insurer_id == "asisa")
    refused = eligibility.check_patient_rules(
        catalogue,
        patient,
        specialty_id="physiotherapy",
        location_id=None,
        plan=asisa,
        today=date(2026, 9, 18),
    )
    assert refused is not None
    assert refused.reason == "location_not_covered"

    allowed = eligibility.check_patient_rules(
        catalogue,
        patient,
        specialty_id="general_practice",  # at Centro and Norte, both covered
        location_id=None,
        plan=asisa,
        today=date(2026, 9, 18),
    )
    assert allowed is None


def test_a_provider_refusing_a_plan_redirects_to_one_who_takes_it(catalogue):
    """Dra. Iglesias does not take DKV. That is a redirect, not the end of the call."""
    iglesias = next(p for p in catalogue.providers if p.provider_id == "PR04")
    dkv = next(p for p in catalogue.insurance_plans if p.insurer_id == "dkv")
    verdict = eligibility.check_provider_rules(
        catalogue,
        iglesias,
        specialty_id="dermatology",
        location_id=None,
        plan=dkv,
        today=date(2026, 9, 18),
    )
    assert verdict is not None
    assert verdict.reason == "provider_not_in_network"
    # The fixtures hold one dermatologist; live there is a second who takes DKV.
    assert all(p.provider_id != "PR04" for p in verdict.redirect_to)


# ---------------------------------------------------------------------------
# The two plan rules the catalogue cannot express (problem 6, shapes four and
# five). ``ClinicPlanResponse`` has no referral flag and no allowance, so they
# reach us only as ``/availability``'s ``blocked[].restriction``. The tests
# below pin three things: the fake answers the way the platform does, the
# reason submitted is that restriction id verbatim, and nothing in the rules
# lane derives either of them from anything else.
# ---------------------------------------------------------------------------


def test_the_two_plan_rules_are_never_derived_from_the_catalogue(catalogue):
    """Even a plan record carrying the two contract fields yields no verdict.

    ``InsurancePlanRecord.referral_required`` and ``yearly_allowance`` exist in
    the contract but the platform never fills them. Reading a reason off them
    would be a guess, so the patient rules say nothing and leave the answer to
    ``/availability``.
    """
    patient = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00300")
    mapfre = next(p for p in catalogue.insurance_plans if p.insurer_id == "mapfre")
    strict = mapfre.model_copy(update={"referral_required": True, "yearly_allowance": 0})
    verdict = eligibility.check_patient_rules(
        catalogue,
        patient,
        specialty_id="orthopaedics",
        location_id=None,
        plan=strict,
        today=date(2026, 9, 18),
    )
    assert verdict is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("patient_id", "specialty_id", "restriction"),
    [
        ("P00300", "orthopaedics", "insurer_referral_required"),
        ("P00301", "general_practice", "allowance_exhausted"),
    ],
)
async def test_the_fake_availability_names_the_plan_rule_in_blocked(
    patient_id, specialty_id, restriction
):
    """Like the platform: every provider the rule stops is in ``blocked`` with
    the restriction id, and none of their slots are offered."""
    avail = await FakeClinicClient().availability(
        date_from=date(2026, 9, 21),
        date_to=date(2026, 9, 25),
        specialty_id=specialty_id,
        patient_id=patient_id,
    )
    assert avail.blocked, "the plan rule has to be named"
    assert {b.restriction for b in avail.blocked} == {restriction}
    assert {b.reason for b in avail.blocked} == {restriction}
    assert avail.slots == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("from_number", "patient_id", "specialty_id", "restriction"),
    [
        ("+34611222333", "P00300", "orthopaedics", "insurer_referral_required"),
        ("+34622333444", "P00301", "general_practice", "allowance_exhausted"),
    ],
)
async def test_the_reason_submitted_is_the_restriction_id_verbatim(
    tmp_path, from_number, patient_id, specialty_id, restriction
):
    clinic = RecordingClinic()
    ctx = make_ctx(tmp_path, clinic, from_number=from_number)
    avail = await clinic.availability(
        date_from=date(2026, 9, 19),
        date_to=date(2026, 10, 1),
        specialty_id=specialty_id,
        patient_id=patient_id,
    )

    verdict = await check_eligibility(
        ctx, CheckEligibilityInput(patient_id=patient_id, specialty_id=specialty_id)
    )

    assert verdict.allowed is False
    assert verdict.rejection is not None
    assert verdict.rejection.reason == restriction
    assert verdict.rejection.reason == avail.blocked[0].restriction
    assert verdict.note == ""
    assert verdict.skipped_checks == []


@pytest.mark.asyncio
async def test_a_plan_wide_rule_offers_nobody_to_redirect_to(tmp_path):
    """Rafael asks for Dra. Ortiz by name. Dr. Sáez is on the same exhausted
    plan, so offering him would be the same refusal one call later."""
    ctx = make_ctx(tmp_path, RecordingClinic(), from_number="+34622333444")

    verdict = await check_eligibility(
        ctx,
        CheckEligibilityInput(
            patient_id="P00301", specialty_id="general_practice", provider_id="PR01"
        ),
    )

    assert verdict.rejection is not None
    assert verdict.rejection.reason == "allowance_exhausted"
    assert verdict.redirect_to == []


@pytest.mark.asyncio
async def test_a_second_policy_is_the_way_past_a_plan_rule(tmp_path):
    """Problem 17 on top of problem 6: name Sanitas and the same request books."""
    ctx = make_ctx(tmp_path, RecordingClinic(), from_number="+34611222333")

    verdict = await check_eligibility(
        ctx,
        CheckEligibilityInput(patient_id="P00300", specialty_id="orthopaedics", insurer="sanitas"),
    )

    assert verdict.allowed is True
    assert verdict.rejection is None


# ---------------------------------------------------------------------------
# The lookup behind those rules: where the directory record comes from.
#
# ``GET /api/v1/directory`` searches on name, national_id, phone or
# date_of_birth and on nothing else. A parameter-less call is a 422 live, which
# is exactly what ``_patient`` used to make: the record came back ``None`` on
# every real call and every rule above this line silently stood down.
# ---------------------------------------------------------------------------


class RecordingClinic(FakeClinicClient):
    """A fake that remembers how each ``/directory`` query was asked."""

    def __init__(self) -> None:
        super().__init__()
        self.directory_calls: list[dict] = []

    async def directory(self, **kwargs):
        self.directory_calls.append(kwargs)
        return await super().directory(**kwargs)


def make_ctx(tmp_path, clinic: FakeClinicClient, from_number: str | None) -> ToolContext:
    return ToolContext(
        call_id="CA-rules",
        now=datetime(2026, 9, 18, 9, 0, tzinfo=MADRID),
        from_number=from_number,
        clinic=clinic,
        log=CallLog("CA-rules", tmp_path / "calls.jsonl"),
    )


def logged(ctx: ToolContext) -> list[dict]:
    path = ctx.log.path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_the_lookup_never_makes_a_parameter_less_directory_call(tmp_path):
    """The bug itself: no query at all is a 422 live, not the whole directory."""
    clinic = RecordingClinic()
    ctx = make_ctx(tmp_path, clinic, from_number="+34612345678")

    await check_eligibility(
        ctx, CheckEligibilityInput(patient_id="P00042", specialty_id="dermatology")
    )

    assert clinic.directory_calls, "the record has to be looked up somehow"
    for call in clinic.directory_calls:
        given = {k: v for k, v in call.items() if v not in (None, "")}
        assert given, "a directory query with nothing to search on is a 422 live"
        # And it is the one query a bare patient_id can build: the calling line.
        assert "phone" in given


@pytest.mark.asyncio
async def test_the_age_rule_fires_when_the_record_is_in_hand(tmp_path):
    """Lucas is six. General practice takes fourteen and over."""
    ctx = make_ctx(tmp_path, RecordingClinic(), from_number="+34612345678")

    verdict = await check_eligibility(
        ctx, CheckEligibilityInput(patient_id="P00107", specialty_id="general_practice")
    )

    assert verdict.allowed is False
    assert verdict.rejection is not None
    assert verdict.rejection.reason == "not_eligible_age"
    assert verdict.note == ""
    assert any(p.specialty_id == "paediatrics" for p in verdict.redirect_to)


@pytest.mark.asyncio
async def test_the_referral_rule_fires_when_the_record_is_in_hand(tmp_path):
    """Marta holds no dermatology referral; Antonio does. Same query, two answers."""
    without = make_ctx(tmp_path, RecordingClinic(), from_number="+34612345678")
    refused = await check_eligibility(
        without, CheckEligibilityInput(patient_id="P00042", specialty_id="dermatology")
    )
    assert refused.allowed is False
    assert refused.rejection is not None
    assert refused.rejection.reason == "referral_required"

    holder = make_ctx(tmp_path, RecordingClinic(), from_number="+34655555555")
    allowed = await check_eligibility(
        holder,
        CheckEligibilityInput(patient_id="P00200", specialty_id="dermatology", insurer="sanitas"),
    )
    assert allowed.allowed is True
    assert allowed.rejection is None


@pytest.mark.asyncio
async def test_the_record_identity_already_fetched_costs_no_second_query(tmp_path):
    """A real call has already looked the caller up. The rules reuse that record."""
    clinic = RecordingClinic()
    ctx = make_ctx(tmp_path, clinic, from_number="+34612345678")

    found = await find_patient(
        ctx, FindPatientInput(name="Marta Ruiz", date_of_birth=date(1985, 3, 12))
    )
    assert found.status == "found"
    after_identity = len(clinic.directory_calls)

    verdict = await check_eligibility(
        ctx, CheckEligibilityInput(patient_id="P00042", specialty_id="dermatology")
    )

    assert len(clinic.directory_calls) == after_identity, "the rules re-fetched a record they had"
    assert verdict.rejection is not None
    assert verdict.rejection.reason == "referral_required"


@pytest.mark.asyncio
async def test_a_missing_record_is_logged_and_noted_rather_than_passed_over(tmp_path):
    """Nothing to look the id up with: the rules stand down, and they say so."""
    clinic = RecordingClinic()
    ctx = make_ctx(tmp_path, clinic, from_number=None)

    verdict = await check_eligibility(
        ctx, CheckEligibilityInput(patient_id="P00042", specialty_id="dermatology")
    )

    assert clinic.directory_calls == [], "there is no legal query to make without a number"
    # Standing down is not a refusal: /availability is the authority when the
    # record is not in hand, and it applies the same rules server-side.
    assert verdict.skipped_checks == NO_RECORD_SKIPPED
    assert verdict.note == ""
    events = [e for e in logged(ctx) if e["kind"] == "rules.patient_missing"]
    assert events and events[0]["patient_id"] == "P00042"
    assert events[0]["searched_phone"] is False


@pytest.mark.asyncio
async def test_an_id_that_cannot_be_placed_is_looked_up_once(tmp_path):
    """One miss costs one query, however many times the rules ask."""
    clinic = RecordingClinic()
    ctx = make_ctx(tmp_path, clinic, from_number="+34612345678")
    args = CheckEligibilityInput(patient_id="P99999", specialty_id="general_practice")

    first = await check_eligibility(ctx, args)
    calls_after_first = len(clinic.directory_calls)
    second = await check_eligibility(ctx, args)

    assert first.skipped_checks == NO_RECORD_SKIPPED
    assert second.skipped_checks == NO_RECORD_SKIPPED
    assert len(clinic.directory_calls) == calls_after_first == 1
