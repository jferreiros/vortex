"""Problem 16: the catalogue answers the caller asks for before they commit.

The helpers are unit-tested here; the ``clinic_facts`` tool built on them has
its cases in ``evals/logic/cases/rules.yaml`` and the booking that follows an
answer in ``evals/conversation/scenarios/questions.yaml``.

Each test is a question from a published case, and the failure mode is the one
the problem names: an answer the caller then books on, that cannot be booked.
"""

from __future__ import annotations

from datetime import date

import pytest

from vortex.clinic.client import FakeClinicClient
from vortex.contract import ClinicFactsInput
from vortex.rules import facts


@pytest.fixture
def catalogue():
    return FakeClinicClient()._catalogue


def test_only_centro_opens_on_a_saturday(catalogue):
    """ "Which of your clinics is open on a Saturday?" Naming Norte loses the case."""
    assert [s.location_id for s in facts.saturday_sites(catalogue)] == ["centro"]


def test_no_site_opens_on_a_sunday(catalogue):
    assert all(not facts.opens_on(site, 6) for site in catalogue.locations)


def test_getafe_is_the_sur_site(catalogue):
    """ "Do you have a clinic in Getafe?" — matched on the published address."""
    site = facts.site_by_town(catalogue, "Getafe")
    assert site is not None
    assert site.location_id == "sur"


def test_a_town_with_no_clinic_answers_nothing(catalogue):
    assert facts.site_by_town(catalogue, "Cuenca") is None


def test_which_clinics_see_children(catalogue):
    """Paediatrics sits at Centro only; a caller sent to Sur cannot book."""
    assert [s.location_id for s in facts.sites_for_specialty(catalogue, "paediatrics")] == [
        "centro"
    ]


def test_which_dermatologist_consults_at_centro(catalogue):
    found = facts.providers_at(catalogue, "centro", "dermatology")
    assert [p.name for p in found] == ["Dra. Iglesias"]


def test_how_many_orthopaedic_surgeons_and_where(catalogue):
    surgeons = facts.providers_in_specialty(catalogue, "orthopaedics")
    assert len(surgeons) == 1
    assert surgeons[0].location_ids == ["sur"]


TODAY = date(2026, 9, 18)


def test_answer_names_only_centro_for_a_saturday(catalogue):
    """The tool's answer is what the model reads back. Norte in it loses the case."""
    out = facts.answer(catalogue, ClinicFactsInput(weekday="saturday"), TODAY)
    assert [s.location_id for s in out.sites] == ["centro"]
    assert out.rejection is None
    assert "saturday" in out.sites[0].open_days


def test_answer_for_a_sunday_is_empty_and_carries_the_closure_reason(catalogue):
    out = facts.answer(catalogue, ClinicFactsInput(weekday="sunday"), TODAY)
    assert out.sites == []
    assert out.rejection is not None and out.rejection.reason == "clinic_closed"


def test_answer_lists_who_sits_at_a_site_and_flags_leave(catalogue):
    """ "Which doctors are at Norte?" — both, with Requena's leave on the record."""
    out = facts.answer(catalogue, ClinicFactsInput(location_id="norte"), TODAY)
    assert [s.location_id for s in out.sites] == ["norte"]
    by_id = {p.provider_id: p for p in out.sites[0].providers}
    assert set(by_id) == {"PR02", "PR07"}
    assert by_id["PR02"].on_leave_until is None
    assert by_id["PR07"].on_leave_until == date(2026, 9, 30)


def test_answer_narrows_a_site_to_the_specialty_asked(catalogue):
    out = facts.answer(
        catalogue, ClinicFactsInput(location_id="centro", specialty_id="dermatology"), TODAY
    )
    assert [p.name for p in out.sites[0].providers] == ["Dra. Iglesias"]


def test_answer_finds_the_site_in_a_town_and_says_when_it_shuts(catalogue):
    out = facts.answer(catalogue, ClinicFactsInput(town="Getafe"), TODAY)
    assert [s.location_id for s in out.sites] == ["sur"]
    friday = [h for h in out.sites[0].hours if h.weekday == 4]
    assert [f"{h.closes:%H:%M}" for h in friday] == ["14:00"]


def test_answer_for_an_unknown_town_is_empty_without_a_rule(catalogue):
    out = facts.answer(catalogue, ClinicFactsInput(town="Cuenca"), TODAY)
    assert out.sites == [] and out.rejection is None


def test_answer_for_a_specialty_nobody_offers_names_the_rule(catalogue):
    out = facts.answer(catalogue, ClinicFactsInput(specialty_id="cardiology"), TODAY)
    assert out.sites == []
    assert out.rejection is not None and out.rejection.reason == "type_not_offered"


def test_answer_carries_the_network_closure(catalogue):
    out = facts.answer(catalogue, ClinicFactsInput(), TODAY)
    assert date(2026, 10, 12) in out.closure_days
    assert len(out.sites) == 3


def test_the_fact_sheet_states_the_saturday_rule_and_the_closure(catalogue):
    sheet = facts.fact_sheet(catalogue)
    assert "Open on Saturday: Arenal Centro." in sheet
    assert "No site opens on a Sunday." in sheet
    assert "2026-10-12" in sheet  # Fiesta Nacional, network-wide


def test_the_fact_sheet_refuses_to_state_a_doctors_weekdays(catalogue):
    """The catalogue says where a doctor sits, never when. Inventing a day is a
    booking the caller then asks for and cannot have."""
    sheet = facts.fact_sheet(catalogue)
    assert "find_slots" in sheet


@pytest.mark.asyncio
async def test_consulting_weekdays_comes_from_real_slots():
    """ "Which days is she there?" is a diary fact, read off availability."""
    from datetime import date

    clinic = FakeClinicClient()
    availability = await clinic.availability(
        date_from=date(2026, 9, 21), date_to=date(2026, 9, 27), provider_id="PR04"
    )
    # Dra. Iglesias sits at Centro, which opens Monday-Saturday.
    assert facts.consulting_weekdays(availability, "PR04") == [0, 1, 2, 3, 4, 5]
    assert facts.consulting_weekdays(availability, "PR01") == []
