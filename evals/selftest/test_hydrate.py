"""Isolated synthetic-data pack: public cases, diaries, per-problem CallLog JSONL."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from evals.corpus.catalogue import PROBLEMS, load
from evals.corpus.hydrate import (
    SYNTHETIC_DATA_DIR,
    _parse_spoken_slot,
    build,
    identities_in_case,
)
from evals.corpus.probes import RED_FLAGS, REFUSAL_SHAPES, TRIAGE_TABLE, date_phrases
from vortex.clinic.client import FakeClinicClient


def _log_events(problem_id: str) -> list[dict]:
    path = SYNTHETIC_DATA_DIR / "logs" / f"{problem_id}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_pack_covers_every_published_patient_and_appointment() -> None:
    roster = load()
    patients, appointments, manifest, logs = build(roster)
    public_problems = {pid for pid in PROBLEMS if roster.by_problem(pid)}
    assert public_problems <= set(logs)
    book_ids = {
        action["patient_id"]
        for case in roster.cases
        for alt in case.acceptable
        for action in alt
        if action.get("patient_id")
    }
    assert book_ids <= {p["patient_id"] for p in patients}
    diary_ids = {
        action["appointment_id"]
        for case in roster.cases
        for alt in case.acceptable
        for action in alt
        if action.get("appointment_id")
    }
    assert diary_ids <= {a["appointment_id"] for a in appointments}
    assert manifest["roster_cases"] == len(roster.cases)
    assert "P00001" in {p["patient_id"] for p in patients}


def test_committed_pack_matches_the_generator() -> None:
    patients, appointments, _manifest, logs = build()
    patients_path = SYNTHETIC_DATA_DIR / "patients.json"
    appointments_path = SYNTHETIC_DATA_DIR / "appointments.json"
    on_disk_patients = json.loads(patients_path.read_text(encoding="utf-8"))
    on_disk_appts = json.loads(appointments_path.read_text(encoding="utf-8"))
    assert on_disk_patients == patients
    assert on_disk_appts == appointments
    for problem_id, events in logs.items():
        assert _log_events(problem_id) == events


def test_every_problem_has_a_jsonl() -> None:
    logged = {path.stem for path in (SYNTHETIC_DATA_DIR / "logs").glob("*.jsonl")}
    public = {pid for pid, _meta in PROBLEMS.items() if pid != "switchboard"}
    assert public <= logged
    assert "switchboard" in logged
    assert "all" not in logged


def test_probe_logs_cover_documented_varieties() -> None:
    phrases = {event.get("phrase") for event in _log_events("when_exactly") if event.get("phrase")}
    assert {p.phrase for p in date_phrases()} <= phrases

    triage_ids = {
        event["probe_id"]
        for event in _log_events("triage")
        if event.get("kind") == "call.started" and event.get("source") == "probe"
    }
    assert len([p for p in triage_ids if p.startswith("triage.route.")]) == len(TRIAGE_TABLE)
    assert len([p for p in triage_ids if p.startswith("triage.red_flag.")]) == len(RED_FLAGS)

    rule_reasons = {
        event["payload"]["reason"]
        for event in _log_events("the_rules")
        if event.get("kind") == "submit.result" and event.get("source") == "probe"
        if event.get("payload", {}).get("reason")
    }
    assert {reason for _label, reason in REFUSAL_SHAPES} <= rule_reasons


def test_fake_client_default_stays_on_fixtures() -> None:
    plain = FakeClinicClient()
    assert all(p.patient_id != "P00009" for p in plain._patients)
    assert any(p.patient_id == "P00042" for p in plain._patients)


def test_data_dir_client_finds_a_published_patient_and_diary() -> None:
    async def _run() -> None:
        clinic = FakeClinicClient(data_dir=SYNTHETIC_DATA_DIR)
        found = await clinic.directory(national_id="48064716Y")
        assert found and found[0].patient_id == "P00001"
        assert all(p.patient_id != "P00042" for p in clinic._patients)
        diary = await clinic.appointments("P00005", when="all")
        assert any(row.appointment_id == "A001101" for row in diary)

    asyncio.run(_run())


def test_hydrate_writes_only_under_out_dir(tmp_path: Path) -> None:
    from evals.corpus.hydrate import build, write_pack

    patients, appointments, manifest, logs = build()
    write_pack(
        patients=patients,
        appointments=appointments,
        manifest=manifest,
        logs=logs,
        out_dir=tmp_path,
    )
    assert (tmp_path / "patients.json").exists()
    assert (tmp_path / "appointments.json").exists()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "logs" / "simple_booking.jsonl").exists()


def test_spoken_appointment_parses_site_and_time() -> None:
    parsed = _parse_spoken_slot(
        "Tuesday 13 October at 12:00 with Dra. Elena Iglesias at Arenal Sur"
    )
    assert parsed is not None
    assert parsed["location_id"] == "sur"
    assert parsed["start_time"].startswith("2026-10-13T12:00:00")
    assert "Iglesias" in parsed["provider_name"]


def test_every_public_case_has_identities_or_is_register_only() -> None:
    roster = load()
    for case in roster.cases:
        people = identities_in_case(case)
        if case.problem_id == "the_new_patient":
            assert people
            continue
        assert people, case.id
