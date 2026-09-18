"""The rule engine's edges, where an eval case would only see the verdict.

The evals check what ``check_eligibility`` answers. These check the arithmetic
and the precedence behind it — the boundary the age rule turns on, and the
self-pay rule that stops a refusal being talked around.
"""

from __future__ import annotations

from datetime import date

import pytest

from vortex.clinic.client import FakeClinicClient
from vortex.rules import eligibility


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
    """Ten plans live; five in the fixtures. An unknown one stands down."""
    patient = next(p for p in FakeClinicClient()._patients if p.patient_id == "P00042")
    assert eligibility.resolve_plan(catalogue, patient, "mapfre") is None


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
