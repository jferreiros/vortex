"""Problem 16: the catalogue answers the caller asks for before they commit.

These are unit tests rather than ``evals/logic`` cases because the fact sheet
is not a contract tool — the conversation lane reads it into the system prompt.
See the lane report: a ``clinic_facts`` tool would need a contract change.

Each test is a question from a published case, and the failure mode is the one
the problem names: an answer the caller then books on, that cannot be booked.
"""

from __future__ import annotations

import pytest

from vortex.clinic.client import FakeClinicClient
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
