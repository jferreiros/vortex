"""The fixture roster has the real clinic's shape.

Problem 11 is the one problem whose private pool differs from its public
cases: Catalan comes up far more often, and the booked provider must speak it.
The filter in ``find_slots(language=...)`` is only as good as the roster it
runs against, so these pin the published facts the offline suite rehearses on:
twelve providers, six specialties, everyone speaks Spanish, exactly four speak
Catalan, one per specialty that has one.
"""

from __future__ import annotations

import pytest

from vortex.clinic import fixtures
from vortex.clinic.client import FakeClinicClient
from vortex.contract import Catalogue

CATALAN_SPEAKERS = {"PR01", "PR08", "PR10", "PR12"}


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return FakeClinicClient()._catalogue


def test_twelve_providers_over_six_specialties(catalogue: Catalogue) -> None:
    assert len(catalogue.providers) == 12
    assert len({p.provider_id for p in catalogue.providers}) == 12
    specialties = {p.specialty_id for p in catalogue.providers}
    assert specialties == {s.specialty_id for s in catalogue.specialties}
    assert len(specialties) == 6


def test_every_provider_speaks_spanish(catalogue: Catalogue) -> None:
    assert all("es" in p.languages for p in catalogue.providers)


def test_exactly_four_speak_catalan_one_per_specialty(catalogue: Catalogue) -> None:
    speakers = {p.provider_id: p.specialty_id for p in catalogue.providers if "ca" in p.languages}
    assert set(speakers) == CATALAN_SPEAKERS
    # One per specialty: the language filter narrows a request to one doctor,
    # never to nobody in a specialty that has a Catalan speaker.
    assert sorted(speakers.values()) == [
        "dermatology",
        "general_practice",
        "orthopaedics",
        "paediatrics",
    ]


def test_no_catalan_speaker_in_physiotherapy_or_gynaecology(catalogue: Catalogue) -> None:
    """The two single-provider specialties: a Catalan-only caller has nobody there."""
    for specialty in ("physiotherapy", "gynaecology"):
        pool = [p for p in catalogue.providers if p.specialty_id == specialty]
        assert len(pool) == 1
        assert "ca" not in pool[0].languages


def test_every_name_cross_reference_resolves() -> None:
    """The raw payload links by name; a name nobody has is a silent hole."""
    names = {p["name"] for p in fixtures.PROVIDERS}
    for group in (fixtures.LOCATIONS, fixtures.SPECIALTIES, fixtures.APPOINTMENT_TYPES):
        for entry in group:
            assert set(entry["provider_names"]) <= names, entry["id"]
    for provider in fixtures.PROVIDERS:
        sites = {
            loc["name"] for loc in fixtures.LOCATIONS if provider["name"] in loc["provider_names"]
        }
        assert sites == set(provider["location_names"]), provider["id"]
        specialty = next(s for s in fixtures.SPECIALTIES if provider["name"] in s["provider_names"])
        assert specialty["id"] == provider["specialty_id"], provider["id"]
        types = {
            t["name"] for t in fixtures.APPOINTMENT_TYPES if provider["name"] in t["provider_names"]
        }
        assert types == set(provider["appointment_type_names"]), provider["id"]


def test_the_second_dermatologist_takes_dkv(catalogue: Catalogue) -> None:
    """Dra. Iglesias refuses DKV; Dr. Vilar takes it. The redirect exists offline too."""
    by_id = {p.provider_id: p for p in catalogue.providers}
    assert "dkv" in by_id["PR04"].insurer_ids_refused
    assert "dkv" in by_id["PR12"].insurer_ids_accepted
    assert by_id["PR12"].specialty_id == "dermatology"
