"""Tests for the discover sweep's offline half.

The sweep runs live, so what can be pinned offline is the shape of its
verdict: a reached reason is reported with a real query, an unreached one
with the line that says why, and the probe that proves `location_hours`
unreportable records nothing at all against a clinic whose engine — like the
real one — answers a shut window with empty availability and empty `blocked`.
"""

from __future__ import annotations

import asyncio

from evals.corpus.discover import (
    _seed_names,
    _specialty_type,
    _type_gaps,
    main,
    probe_unreportable,
    report,
)
from vortex.clinic.client import FakeClinicClient, _pick_type, check_directory_query
from vortex.contract import PatientRecord
from vortex.settings import reset_settings


def _catalogue():
    return asyncio.run(FakeClinicClient().catalogue())


# ---- the report ---------------------------------------------------------------


def test_a_reached_reason_is_named_with_a_real_query(capsys) -> None:
    sample = {"patient_id": "P00016", "specialty_id": "dermatology", "via": "directory"}
    report({"allowance_exhausted": [sample]}, {})
    out = capsys.readouterr().out
    assert "allowance_exhausted" in out
    assert "P00016" in out
    assert "impossible" not in out


def test_an_unreached_reason_says_why_against_this_clinic(capsys) -> None:
    report({}, {"location_hours": "the engine reports no rule: 16 shut windows"})
    out = capsys.readouterr().out
    assert "location_hours" in out
    assert "impossible from the API" in out
    assert "16 shut windows" in out


def test_a_reason_no_sweep_reached_is_declared_not_dropped(capsys) -> None:
    report({}, {})
    out = capsys.readouterr().out
    assert out.count("not reached by this sweep") == 11


# ---- the harvest --------------------------------------------------------------


def test_every_seed_name_is_a_valid_directory_query() -> None:
    """A seed that fails the platform's own 422 check wastes its query."""
    for name in _seed_names():
        check_directory_query(name, None, None, None)


# ---- the type resolution the type_not_offered probe stands on -----------------


def test_the_sweep_resolves_the_same_type_the_client_resolves() -> None:
    catalogue = _catalogue()
    new = PatientRecord(patient_id="P00001", given_name="T", first_surname="T")
    visited = new.model_copy(update={"has_visited_before": True})
    for specialty in {p.specialty_id for p in catalogue.providers}:
        for patient in (new, visited):
            resolved = _specialty_type(catalogue, specialty, patient.has_visited_before)
            picked = _pick_type(catalogue, specialty, patient)
            assert resolved == (picked.appointment_type_id if picked else None)


def test_a_provider_missing_the_resolved_type_is_flagged_as_a_gap() -> None:
    """The gap is what would make type_not_offered producible; the real
    catalogue has none, so the probe must see none offline."""
    catalogue = _catalogue()
    assert _type_gaps(catalogue) == []
    provider = next(p for p in catalogue.providers if p.specialty_id == "dermatology")
    stripped = provider.model_copy(
        update={
            "appointment_type_ids": [t for t in provider.appointment_type_ids if "first" not in t]
        }
    )
    broken = catalogue.model_copy(
        update={
            "providers": [
                stripped if p.provider_id == provider.provider_id else p
                for p in catalogue.providers
            ]
        }
    )
    gaps = _type_gaps(broken)
    assert any(
        gap["provider_id"] == provider.provider_id and "first" in gap["appointment_type_id"]
        for gap in gaps
    )


# ---- the shut-window probe -----------------------------------------------------


def test_a_shut_window_never_produces_a_rule_offline() -> None:
    """The property that makes location_hours unreportable: a window the site
    is shut for the whole of answers with empty availability, empty blocked —
    the engine names no rule for it, so the refusal is the agent's to derive."""
    catalogue = _catalogue()
    samples: dict[str, list[dict]] = {}

    def record(reason: str, **sample) -> None:
        samples.setdefault(reason, []).append(sample)

    stats = asyncio.run(
        probe_unreportable(FakeClinicClient(), asyncio.Semaphore(4), catalogue, [], record)
    )
    assert samples == {}
    assert stats["location_hours"]["windows"] > 0
    assert stats["location_hours"]["blocked"] == 0
    assert stats["type_not_offered"]["gaps"] == 0


# ---- the gate -------------------------------------------------------------------


def test_the_sweep_refuses_without_a_live_clinic(monkeypatch) -> None:
    monkeypatch.setenv("PLATFORM_API_KEY", "")
    monkeypatch.setenv("VORTEX_CLINIC_MODE", "fake")
    reset_settings()
    try:
        assert main([]) == 2
    finally:
        reset_settings()
