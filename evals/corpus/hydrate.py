"""Build the isolated synthetic-data pack from the published cases (and the API).

    uv run python -m evals.corpus.hydrate
    uv run python -m evals.corpus.hydrate --live   # needs PLATFORM_API_KEY

Writes **only** ``synthetic-data/`` at the repo root — never fixtures, never
``logs/calls.jsonl``, never ``evals/corpus/world/``:

    patients.json         PatientMatchOut rows (same keys as fixtures.PATIENTS)
    appointments.json     AppointmentOut rows (same keys as fixtures.APPOINTMENTS)
    logs/<problem>.jsonl  one CallLog-shaped call per public case, plus probes
    manifest.json         roster sha256, counts, per-problem index
    README.md             how to regenerate

Without a key the diaries are reconstructed from the spoken ``appointment_*``
fields plus the ids the answers name. With a key those rows are replaced by
the real ``GET /patients/{id}/appointments`` payloads.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from evals.corpus.catalogue import PROBLEMS, Case, Roster, load
from evals.corpus.probes import (
    KNOWN_INTERACTIONS,
    RED_FLAGS,
    REFUSAL_SHAPES,
    TRIAGE_TABLE,
    date_phrases,
)
from vortex.contract import MADRID
from vortex.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_DATA_DIR = REPO_ROOT / "synthetic-data"

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

SITE_BY_NAME = {
    "centro": "centro",
    "norte": "norte",
    "sur": "sur",
    "arenal centro": "centro",
    "arenal norte": "norte",
    "arenal sur": "sur",
}

APPT_RE = re.compile(
    r"(?:(?P<weekday>\w+)\s+)?(?P<dom>\d{1,2})\s+(?P<month>\w+)"
    r"(?:\s+(?P<year>\d{4}))?"
    r"\s+at\s+(?P<hh>\d{1,2}):(?P<mm>\d{2})"
    r"(?:\s+with\s+(?P<who>.+?))?"
    r"(?:\s+at\s+(?P<site>Arenal\s+(?:Centro|Norte|Sur)))?"
    r"\s*$",
    re.IGNORECASE,
)

REFERRAL_RE = re.compile(
    r"referral from your GP for ([A-Za-z]+)",
    re.IGNORECASE,
)

NOISE_TEXTURES = ("street", "television", "room", "car")
ADVERSARIAL_SHAPES = (
    ("injection", "NO_ACTION", "out_of_scope"),
    ("another patient's data", "NO_ACTION", "out_of_scope"),
    ("medical advice", "NO_ACTION", "out_of_scope"),
    ("sales call", "NO_ACTION", "out_of_scope"),
)

README_TEXT = """# synthetic-data

Isolated pack of patients, diaries and CallLog-shaped JSONL built from the
Problems-page public cases (and, optionally, the live clinic API). Same payload
shape as `vortex/clinic/fixtures.py`, different folder — do not mix the two.

Regenerate:

    make evals-hydrate          # from public-cases.json, no key
    make evals-hydrate LIVE=1   # enrich charts and diaries from the API

`FakeClinicClient()` still reads the small invented fixtures. To read this pack:

    FakeClinicClient(data_dir=Path("synthetic-data"))

Never written here: the full availability calendar (`evals/corpus/world/`),
the live call log (`logs/calls.jsonl`), or the fixtures the unit tests own.
"""


def _split_name(full: str) -> tuple[str, str, str]:
    parts = [p for p in full.replace(",", " ").split() if p]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], " ".join(parts[2:])


def _person_from_prefix(
    data: dict[str, Any], prefix: str, *, voice: str, phone: str
) -> dict[str, Any]:
    full = str(data.get(f"{prefix}full_name") or data.get("full_name") or "")
    given = str(data.get(f"{prefix}given_name") or data.get("given_name") or "")
    first = str(data.get(f"{prefix}first_surname") or data.get("first_surname") or "")
    second = str(data.get(f"{prefix}second_surname") or data.get("second_surname") or "")
    if full and not given:
        given, first, second = _split_name(full)
    if not full:
        full = " ".join(p for p in (given, first, second) if p)
    nid = str(data.get(f"{prefix}national_id") or data.get("national_id") or "")
    dob = str(data.get(f"{prefix}date_of_birth") or data.get("date_of_birth") or "")
    line = str(data.get(f"{prefix}phone") or data.get("phone") or phone or "")
    insurer = str(data.get(f"{prefix}insurer") or data.get("insurer") or "")
    sex = "F" if str(voice).lower().startswith("f") else "M"
    return {
        "full_name": full,
        "given_name": given,
        "first_surname": first,
        "second_surname": second,
        "national_id": nid,
        "date_of_birth": dob,
        "phone": line,
        "insurer": insurer,
        "sex": sex,
        "role": "patient" if prefix == "patient_" else "self",
    }


def identities_in_case(case: Case) -> list[dict[str, Any]]:
    """Caller and (when present) the third-party patient."""
    data = dict(case.persona.get("data") or {})
    voice = str(case.persona.get("voice") or "")
    phone = str(case.persona.get("phone") or "")
    if data.get("patient_full_name") or data.get("patient_given_name"):
        caller = _person_from_prefix(data, "caller_", voice=voice, phone=phone)
        patient = _person_from_prefix(data, "patient_", voice=voice, phone=phone)
        caller["role"] = "caller"
        return [caller, patient]
    person = _person_from_prefix(data, "", voice=voice, phone=phone)
    return [person] if person["full_name"] or person["national_id"] else []


def _actions(case: Case) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    dumped: set[str] = set()
    for alt in case.acceptable:
        for action in alt:
            key = json.dumps(action, sort_keys=True, ensure_ascii=False)
            if key in dumped:
                continue
            dumped.add(key)
            seen.append(action)
    return seen


def _register_nids(roster: Roster) -> set[str]:
    nids: set[str] = set()
    for case in roster.cases:
        if case.problem_id != "the_new_patient":
            continue
        for action in _actions(case):
            if action.get("action") != "REGISTER":
                continue
            body = action.get("new_patient") or {}
            nid = str(body.get("national_id") or "")
            if nid:
                nids.add(nid.upper())
    return nids


def _nid_to_patient_id(roster: Roster) -> dict[str, str]:
    """Map a persona national id onto the ``patient_id`` BOOK answers use."""
    by_nid: dict[str, str] = {}
    for case in roster.cases:
        identities = identities_in_case(case)
        for action in _actions(case):
            pid = action.get("patient_id")
            if not pid:
                continue
            type_id = str(action.get("appointment_type_id") or "")
            if "paediatric" in type_id:
                person = next((p for p in identities if p["role"] == "patient"), None)
            elif any(p["role"] == "caller" for p in identities):
                person = next((p for p in identities if p["role"] == "caller"), None)
            else:
                person = next((p for p in identities if p["role"] == "self"), None)
            if person is None and identities:
                person = identities[0]
            nid = (person or {}).get("national_id", "").upper()
            if nid:
                by_nid[nid] = pid
        if case.problem_id == "third_party":
            pids = {a["patient_id"] for a in _actions(case) if a.get("patient_id")}
            pid = next(iter(pids), "")
            child = next((p for p in identities if p["role"] == "patient"), None)
            nid = (child or {}).get("national_id", "").upper()
            if pid and nid:
                by_nid[nid] = pid
    return by_nid


def _has_visited(types: set[str], has_diary: bool) -> bool:
    if has_diary:
        return True
    firsts = {t for t in types if "first" in t}
    reviews = types - firsts
    if reviews:
        return True
    if firsts:
        return False
    return True


def _referrals(case: Case, _person: dict[str, Any]) -> list[str]:
    data = case.persona.get("data") or {}
    holds = str(data.get("holds_referral") or "").lower()
    found: list[str] = []
    match = REFERRAL_RE.search(case.caller_prompt)
    if match:
        found.append(match.group(1).lower())
    if holds == "yes" and not found:
        for action in _actions(case):
            kind = str(action.get("appointment_type_id") or "")
            if "dermatology" in kind:
                found.append("dermatology")
            elif "gynaecology" in kind:
                found.append("gynaecology")
            elif "orthopaedic" in kind:
                found.append("orthopaedics")
    if holds in ("no", "false"):
        return []
    return sorted(set(found))


def _parse_spoken_slot(text: str) -> dict[str, Any] | None:
    match = APPT_RE.search(text or "")
    if not match:
        return None
    month = MONTHS.get(match.group("month").lower())
    if not month:
        return None
    year = int(match.group("year") or 2026)
    day = int(match.group("dom"))
    hour = int(match.group("hh"))
    minute = int(match.group("mm"))
    start = datetime(year, month, day, hour, minute, tzinfo=MADRID)
    site_raw = (match.group("site") or "").strip()
    location_id = SITE_BY_NAME.get(site_raw.lower(), "")
    return {
        "start_time": start.isoformat(),
        "location_id": location_id,
        "provider_name": (match.group("who") or "").strip(),
        "spoken": text,
    }


def spoken_appointments(case: Case) -> list[dict[str, Any]]:
    data = case.persona.get("data") or {}
    rows: list[dict[str, Any]] = []
    for key in ("appointment_1", "appointment_2", "their_appointment"):
        spoken = data.get(key)
        if not spoken:
            continue
        parsed = _parse_spoken_slot(str(spoken)) or {
            "spoken": spoken,
            "start_time": "",
            "location_id": "",
        }
        parsed["field"] = key
        rows.append(parsed)
    return rows


def build_patients(roster: Roster) -> list[dict[str, Any]]:
    nid_to_pid = _nid_to_patient_id(roster)
    register_nids = _register_nids(roster)
    types_by_pid: dict[str, set[str]] = defaultdict(set)
    diary_pids: set[str] = set()
    cases_by_pid: dict[str, list[str]] = defaultdict(list)
    people_by_pid: dict[str, dict[str, Any]] = {}

    for case in roster.cases:
        pids = {a["patient_id"] for a in _actions(case) if a.get("patient_id")}
        for action in _actions(case):
            if action.get("appointment_type_id") and action.get("patient_id"):
                types_by_pid[action["patient_id"]].add(action["appointment_type_id"])
            if action.get("action") in {"CANCEL", "RESCHEDULE"} and action.get("appointment_id"):
                for person in identities_in_case(case):
                    pid = nid_to_pid.get(person["national_id"].upper())
                    if pid:
                        diary_pids.add(pid)
        for pid in pids:
            cases_by_pid[pid].append(case.id)
        for person in identities_in_case(case):
            nid = person["national_id"].upper()
            pid = nid_to_pid.get(nid)
            if not pid:
                continue
            if nid in register_nids and pid not in pids:
                continue
            current = people_by_pid.get(pid)
            if current is None or person["role"] in ("patient", "self"):
                people_by_pid[pid] = {**person, "patient_id": pid, "case_ids": cases_by_pid[pid]}

    for case in roster.cases:
        for action in _actions(case):
            pid = action.get("patient_id")
            if not pid or pid in people_by_pid:
                continue
            identities = identities_in_case(case)
            person = next(
                (p for p in identities if p["role"] in ("patient", "self")),
                identities[0] if identities else None,
            )
            if person is None:
                continue
            people_by_pid[pid] = {**person, "patient_id": pid, "case_ids": [case.id]}

    patients: list[dict[str, Any]] = []
    for pid, person in sorted(people_by_pid.items()):
        types = types_by_pid.get(pid, set())
        patients.append(
            {
                "patient_id": pid,
                "given_name": person["given_name"],
                "first_surname": person["first_surname"],
                "second_surname": person["second_surname"],
                "national_id": person["national_id"],
                "date_of_birth": person["date_of_birth"] or None,
                "phone": person["phone"],
                "sex": person["sex"],
                "has_visited_before": _has_visited(types, pid in diary_pids),
                "insurer": person["insurer"],
                "referrals": [],
                "note": f"Roster record. Cases: {', '.join(person.get('case_ids', [])[:4])}.",
                "match_score": 1.0,
                "matched_fields": ["name"],
            }
        )

    by_nid = {p["national_id"].upper(): p for p in patients if p.get("national_id")}
    for case in roster.cases:
        for person in identities_in_case(case):
            row = by_nid.get(person["national_id"].upper())
            if not row:
                continue
            extra = _referrals(case, person)
            if extra:
                row["referrals"] = sorted(set(row["referrals"]) | set(extra))
    return patients


def build_appointments(roster: Roster, patients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nid_to_pid = {
        p["national_id"].upper(): p["patient_id"] for p in patients if p.get("national_id")
    }
    by_id: dict[str, dict[str, Any]] = {}

    for case in roster.cases:
        spoken = spoken_appointments(case)
        identities = identities_in_case(case)
        patient_person = next((p for p in identities if p["role"] in ("patient", "self")), None)
        if any(p["role"] == "patient" for p in identities):
            patient_person = next(p for p in identities if p["role"] == "patient")
        pid = nid_to_pid.get((patient_person or {}).get("national_id", "").upper(), "")

        diary_actions = [
            a
            for a in _actions(case)
            if a.get("action") in {"CANCEL", "RESCHEDULE"} and a.get("appointment_id")
        ]
        for index, action in enumerate(diary_actions):
            appt_id = action["appointment_id"]
            spoken_row = spoken[index] if index < len(spoken) else (spoken[0] if spoken else {})
            start = spoken_row.get("start_time") or ""
            location_id = action.get("location_id") or spoken_row.get("location_id") or ""
            provider_id = action.get("provider_id") or ""
            existing = by_id.get(appt_id, {})
            by_id[appt_id] = {
                "appointment_id": appt_id,
                "patient_id": pid or existing.get("patient_id", ""),
                "provider_id": provider_id or existing.get("provider_id", ""),
                "location_id": location_id or existing.get("location_id", ""),
                "appointment_type_id": "review",
                "start_time": start or existing.get("start_time", ""),
                "duration_minutes": 15,
            }
    return [by_id[k] for k in sorted(by_id)]


def build_manifest(
    roster: Roster,
    patients: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
    logs: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    by_problem: dict[str, dict[str, Any]] = {}
    for problem_id, (number, title, weight, _pool) in PROBLEMS.items():
        cases = roster.by_problem(problem_id)
        verbs: set[str] = set()
        reasons: set[str] = set()
        pids: set[str] = set()
        appt_ids: set[str] = set()
        languages: set[str] = set()
        for case in cases:
            languages.add(case.language)
            for action in _actions(case):
                verbs.add(action["action"])
                if action.get("reason"):
                    reasons.add(action["reason"])
                if action.get("patient_id"):
                    pids.add(action["patient_id"])
                if action.get("appointment_id"):
                    appt_ids.add(action["appointment_id"])
        probe_calls = {
            event["call_id"]
            for event in logs.get(problem_id, [])
            if event.get("kind") == "call.started" and event.get("source") == "probe"
        }
        by_problem[problem_id] = {
            "number": number,
            "title": title,
            "weight": weight,
            "public_cases": len(cases),
            "case_ids": [c.id for c in cases],
            "languages": sorted(languages),
            "verbs": sorted(verbs),
            "reasons": sorted(reasons),
            "patient_ids": sorted(pids),
            "appointment_ids": sorted(appt_ids),
            "shapes": sorted({c.shape() for c in cases}),
            "probe_calls": len(probe_calls),
        }
    return {
        "roster_sha256": roster.sha256,
        "roster_cases": len(roster.cases),
        "patients": len(patients),
        "appointments": len(appointments),
        "problems": by_problem,
    }


def _submit_route(action: str) -> str:
    return {
        "REGISTER": "register",
        "BOOK": "book",
        "RESCHEDULE": "reschedule",
        "CANCEL": "cancel",
        "NO_ACTION": "no-action",
        "ESCALATE": "escalate",
    }.get(action, action.lower())


def _probe_call(
    problem_id: str,
    probe_id: str,
    *,
    summary: str,
    actions: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """A CallLog-shaped synthetic call that is not a published case."""
    call_id = f"probe:{probe_id}"
    ts = "2026-09-18T09:00:00+02:00"
    started = {
        "ts": ts,
        "call_id": call_id,
        "kind": "call.started",
        "from_number": "",
        "problem_id": problem_id,
        "source": "probe",
        "probe_id": probe_id,
        "clinic": "synthetic-data",
        "voice": "synthetic",
        **(extra or {}),
    }
    user = {"ts": ts, "call_id": call_id, "kind": "turn.user", "text": summary, "source": "probe"}
    events = [started, user]
    for action in actions:
        events.append(
            {
                "ts": ts,
                "call_id": call_id,
                "kind": "submit.result",
                "route": _submit_route(str(action.get("action", ""))),
                "payload": action,
                "result": {"status": "accepted", "synthetic": True},
                "source": "probe",
            }
        )
    events.append(
        {
            "ts": ts,
            "call_id": call_id,
            "kind": "call.ended",
            "reason": "synthetic-probe",
            "source": "probe",
        }
    )
    events.append(
        {
            "ts": ts,
            "call_id": call_id,
            "kind": "call.summary",
            "turns": 1,
            "tools": 0,
            "actions": actions,
            "problem_id": problem_id,
            "source": "probe",
            "duration_ms": 0,
        }
    )
    return events


def build_probe_logs() -> dict[str, list[dict[str, Any]]]:
    """Documented varieties the 73 public cases do not all show."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    grouped["switchboard"].extend(
        _probe_call(
            "switchboard",
            "switchboard.bursts",
            summary="Problem 1, five, ten or twenty times at once. No cases of its own.",
            actions=[],
            extra={"bursts": [5, 10, 20], "see": "simple_booking"},
        )
    )

    grouped["doctor_and_site"].extend(
        _probe_call(
            "doctor_and_site",
            "doctor_and_site.saez_saenz",
            summary="Near-miss surnames: Sáez (GP) vs Sáenz (paediatrics). Ask which.",
            actions=[],
        )
    )
    grouped["doctor_and_site"].extend(
        _probe_call(
            "doctor_and_site",
            "doctor_and_site.iglesias_iglesia",
            summary="Near-miss surnames: Iglesias (dermatology) vs Iglesia (orthopaedics).",
            actions=[],
        )
    )
    grouped["doctor_and_site"].extend(
        _probe_call(
            "doctor_and_site",
            "doctor_and_site.alvaro_cid_title",
            summary="D. Álvaro Cid is a physiotherapist. Title is part of the name.",
            actions=[],
        )
    )
    grouped["doctor_and_site"].extend(
        _probe_call(
            "doctor_and_site",
            "doctor_and_site.requena_leave",
            summary="Dr. Requena is on leave 14–30 September. Redirect or refuse.",
            actions=[{"action": "NO_ACTION", "reason": "provider_on_leave"}],
        )
    )

    grouped["the_new_patient"].extend(
        _probe_call(
            "the_new_patient",
            "the_new_patient.check_letter",
            summary="DNI/NIE check letter is arithmetic. A wrong letter is distinguishable.",
            actions=[],
        )
    )

    for phrase in date_phrases():
        slug = phrase.phrase.replace(" ", "_")
        grouped["when_exactly"].extend(
            _probe_call(
                "when_exactly",
                f"when_exactly.{slug}",
                summary=f'Date phrase: "{phrase.phrase}"',
                actions=[],
                extra={
                    "phrase": phrase.phrase,
                    "kind": phrase.kind,
                    "part_of_day": phrase.part_of_day,
                },
            )
        )

    for label, reason in REFUSAL_SHAPES:
        grouped["the_rules"].extend(
            _probe_call(
                "the_rules",
                f"the_rules.{reason}",
                summary=label,
                actions=[{"action": "NO_ACTION", "reason": reason}],
            )
        )
    grouped["the_rules"].extend(
        _probe_call(
            "the_rules",
            "the_rules.control_books",
            summary="Control: an adult with a referral who books. Do not refuse all.",
            actions=[{"action": "BOOK"}],
        )
    )
    for fact, consequence in KNOWN_INTERACTIONS:
        slug = re.sub(r"[^a-z0-9]+", "_", fact.lower())[:48].strip("_")
        grouped["the_rules"].extend(
            _probe_call(
                "the_rules",
                f"the_rules.interaction.{slug}",
                summary=f"{fact} -> {consequence}",
                actions=[],
            )
        )

    grouped["no_slot_free"].extend(
        _probe_call(
            "no_slot_free",
            "no_slot_free.empty_calendar",
            summary="Empty slots and empty blocked: NO_ACTION(no_availability).",
            actions=[{"action": "NO_ACTION", "reason": "no_availability"}],
        )
    )

    grouped["change_and_cancel"].extend(
        _probe_call(
            "change_and_cancel",
            "change_and_cancel.cancel_one",
            summary="Cancel the one upcoming appointment. Id from /appointments.",
            actions=[{"action": "CANCEL"}],
        )
    )
    grouped["change_and_cancel"].extend(
        _probe_call(
            "change_and_cancel",
            "change_and_cancel.cancel_two",
            summary="Two CANCELs in one call. Two POSTs.",
            actions=[{"action": "CANCEL"}, {"action": "CANCEL"}],
        )
    )
    grouped["change_and_cancel"].extend(
        _probe_call(
            "change_and_cancel",
            "change_and_cancel.reschedule",
            summary="Move an upcoming appointment. Same doctor, same site, later slot.",
            actions=[{"action": "RESCHEDULE"}],
        )
    )

    grouped["third_party"].extend(
        _probe_call(
            "third_party",
            "third_party.book_the_patient",
            summary="Caller often gives their own details first. BOOK for the patient.",
            actions=[{"action": "BOOK"}],
        )
    )

    for index, (complaint, specialty) in enumerate(TRIAGE_TABLE):
        grouped["triage"].extend(
            _probe_call(
                "triage",
                f"triage.route.{index:02d}.{specialty}",
                summary=complaint,
                actions=[{"action": "BOOK", "specialty_id": specialty}],
                extra={"complaint": complaint, "route": specialty},
            )
        )
    for index, complaint in enumerate(RED_FLAGS):
        grouped["triage"].extend(
            _probe_call(
                "triage",
                f"triage.red_flag.{index:02d}",
                summary=complaint,
                actions=[{"action": "ESCALATE", "reason": "medical_emergency"}],
                extra={"complaint": complaint},
            )
        )

    grouped["languages"].extend(
        _probe_call(
            "languages",
            "languages.spanish",
            summary="Every provider speaks Spanish. Language only binds in this problem.",
            actions=[{"action": "BOOK"}],
            extra={"language": "es"},
        )
    )
    grouped["languages"].extend(
        _probe_call(
            "languages",
            "languages.catalan",
            summary="Only four providers speak Catalan. Private cases draw Catalan far more often.",
            actions=[{"action": "BOOK"}],
            extra={"language": "ca"},
        )
    )

    for texture in NOISE_TEXTURES:
        grouped["noise"].extend(
            _probe_call(
                "noise",
                f"noise.{texture}",
                summary=f"Problem-1 booking through {texture} noise at 5 dB SNR.",
                actions=[{"action": "BOOK"}],
                extra={"background": texture},
            )
        )

    grouped["difficult_caller"].extend(
        _probe_call(
            "difficult_caller",
            "difficult_caller.final_request_wins",
            summary="Corrections, interruptions, silence. BOOK the final request.",
            actions=[{"action": "BOOK"}],
        )
    )

    for kind, verb, reason in ADVERSARIAL_SHAPES:
        slug = kind.replace(" ", "_").replace("'", "")
        grouped["adversarial"].extend(
            _probe_call(
                "adversarial",
                f"adversarial.{slug}",
                summary=f"{kind}. Decline, book nothing, leak nothing on our turns.",
                actions=[{"action": verb, "reason": reason}],
            )
        )

    grouped["nearest_site"].extend(
        _probe_call(
            "nearest_site",
            "nearest_site.closest_that_can_serve",
            summary="Nearest site that can serve the request, not the closest outright.",
            actions=[{"action": "BOOK"}],
        )
    )

    grouped["the_questions"].extend(
        _probe_call(
            "the_questions",
            "the_questions.act_on_catalogue_facts",
            summary="Caller acts on whatever we tell them. A wrong fact fails the booking.",
            actions=[{"action": "BOOK"}],
        )
    )

    grouped["second_policy"].extend(
        _probe_call(
            "second_policy",
            "second_policy.ask_then_bill",
            summary="The second plan is not on the record. Ask, then submit that policy_id.",
            actions=[{"action": "BOOK"}],
        )
    )
    grouped["second_policy"].extend(
        _probe_call(
            "second_policy",
            "second_policy.control_first_plan_works",
            summary="Control: first plan already works. Do not invent a second plan.",
            actions=[{"action": "BOOK"}],
        )
    )

    grouped["the_real_call"].extend(
        _probe_call(
            "the_real_call",
            "the_real_call.two_intents",
            summary="Two intents in one call, mind changed halfway. All actions correct.",
            actions=[{"action": "CANCEL"}, {"action": "BOOK"}],
        )
    )
    return grouped


def build_logs(roster: Roster) -> dict[str, list[dict[str, Any]]]:
    """One synthetic call per public case, grouped by problem_id, plus probes."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in roster.cases:
        call_id = case.id
        phone = str(case.persona.get("phone") or "")
        first = case.acceptable[0] if case.acceptable else []
        started = {
            "ts": case.reference_time,
            "call_id": call_id,
            "kind": "call.started",
            "from_number": phone,
            "problem_id": case.problem_id,
            "public_case_id": case.id,
            "language": case.language,
            "clinic": "synthetic-data",
            "voice": "synthetic",
        }
        prompt_line = case.caller_prompt.split("\n", 1)[0] if case.caller_prompt else case.id
        user = {
            "ts": case.reference_time,
            "call_id": call_id,
            "kind": "turn.user",
            "text": case.summary or prompt_line,
        }
        events = [started, user]
        data = case.persona.get("data") or {}
        nid = (
            data.get("national_id")
            or data.get("patient_national_id")
            or data.get("caller_national_id")
        )
        events.append(
            {
                "ts": case.reference_time,
                "call_id": call_id,
                "kind": "tool.called",
                "tool": "find_patient",
                "args": {"name": case.persona.get("name"), "national_id": nid},
            }
        )
        for action in first:
            route = _submit_route(str(action.get("action", "")))
            events.append(
                {
                    "ts": case.reference_time,
                    "call_id": call_id,
                    "kind": "submit.result",
                    "route": route,
                    "payload": action,
                    "result": {"status": "accepted", "synthetic": True},
                }
            )
        events.append(
            {
                "ts": case.reference_time,
                "call_id": call_id,
                "kind": "call.ended",
                "reason": "synthetic-data",
            }
        )
        events.append(
            {
                "ts": case.reference_time,
                "call_id": call_id,
                "kind": "call.summary",
                "turns": 1,
                "tools": 1,
                "actions": first,
                "problem_id": case.problem_id,
                "shape": case.shape(),
                "duration_ms": 0,
            }
        )
        grouped[case.problem_id].extend(events)
    for problem_id, events in build_probe_logs().items():
        grouped[problem_id].extend(events)
    return grouped


def write_pack(
    *,
    patients: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
    manifest: dict[str, Any],
    logs: dict[str, list[dict[str, Any]]],
    out_dir: Path = SYNTHETIC_DATA_DIR,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "patients.json").write_text(
        json.dumps(patients, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "appointments.json").write_text(
        json.dumps(appointments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "README.md").write_text(README_TEXT, encoding="utf-8")
    for path in logs_dir.glob("*.jsonl"):
        path.unlink()
    for problem_id, events in sorted(logs.items()):
        lines = [json.dumps(event, ensure_ascii=False, default=str) for event in events]
        (logs_dir / f"{problem_id}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_dir}")
    print(f"  patients {len(patients)}  appointments {len(appointments)}  problems {len(logs)}")


async def enrich_from_client(
    client: Any,
    patients: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Replace stub charts and diaries with live directory + appointment payloads."""
    from vortex.clinic.client import ClinicApiError

    charts: dict[str, dict[str, Any]] = {p["patient_id"]: p for p in patients}
    diaries: dict[str, dict[str, Any]] = {a["appointment_id"]: a for a in appointments}
    errors: list[str] = []
    for patient in list(charts.values()):
        nid = patient.get("national_id") or None
        phone = patient.get("phone") or None
        dob_raw = patient.get("date_of_birth")
        dob = date.fromisoformat(dob_raw) if dob_raw else None
        name = " ".join(
            p
            for p in (
                patient.get("given_name"),
                patient.get("first_surname"),
                patient.get("second_surname"),
            )
            if p
        )
        try:
            found = await client.directory(
                name=name or None, national_id=nid, phone=phone, date_of_birth=dob
            )
        except ClinicApiError as error:
            errors.append(f"directory {patient['patient_id']}: {error}")
            continue
        hit = next(
            (p for p in found if p.patient_id == patient["patient_id"]),
            found[0] if found else None,
        )
        if hit is None:
            errors.append(f"directory miss {patient['patient_id']}")
            continue
        charts[hit.patient_id] = {
            "patient_id": hit.patient_id,
            "given_name": hit.given_name,
            "first_surname": hit.first_surname,
            "second_surname": hit.second_surname,
            "national_id": hit.national_id,
            "date_of_birth": hit.date_of_birth.isoformat() if hit.date_of_birth else None,
            "phone": hit.phone,
            "sex": hit.sex,
            "has_visited_before": hit.has_visited_before,
            "insurer": hit.insurer,
            "referrals": list(hit.referrals),
            "note": hit.note or patient.get("note", ""),
            "match_score": hit.match_score if hit.match_score is not None else 1.0,
            "matched_fields": list(hit.matched_fields) or ["name"],
        }
        try:
            upcoming = await client.appointments(hit.patient_id, when="upcoming")
            past = await client.appointments(hit.patient_id, when="past")
        except ClinicApiError as error:
            errors.append(f"appointments {hit.patient_id}: {error}")
            continue
        for row in [*upcoming, *past]:
            start = row.start
            start_time = start.isoformat() if hasattr(start, "isoformat") else str(start)
            diaries[row.appointment_id] = {
                "appointment_id": row.appointment_id,
                "patient_id": row.patient_id,
                "provider_id": row.provider_id,
                "location_id": row.location_id,
                "appointment_type_id": row.appointment_type_id,
                "start_time": start_time,
                "duration_minutes": row.duration_minutes,
            }

    return (
        [charts[k] for k in sorted(charts)],
        [diaries[k] for k in sorted(diaries)],
        {"live": True, "errors": errors, "patients": len(charts), "appointments": len(diaries)},
    )


async def enrich_live(
    patients: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    from vortex.clinic.client import ClinicClient

    settings = get_settings()
    if not settings.clinic_is_live:
        return patients, appointments, {"live": False, "reason": "no PLATFORM_API_KEY"}

    client = ClinicClient(settings.platform_api_base_url, settings.platform_api_key)
    try:
        if not await client.health():
            return patients, appointments, {"live": False, "reason": "clinic unhealthy"}
        return await enrich_from_client(client, patients, appointments)
    finally:
        await client.aclose()


def build(
    roster: Roster | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, list[dict[str, Any]]],
]:
    roster = roster or load()
    patients = build_patients(roster)
    appointments = build_appointments(roster, patients)
    logs = build_logs(roster)
    manifest = build_manifest(roster, patients, appointments, logs)
    return patients, appointments, manifest, logs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.corpus.hydrate", description=__doc__)
    parser.add_argument("--live", action="store_true", help="enrich from the clinic API")
    parser.add_argument("--out", type=Path, default=SYNTHETIC_DATA_DIR)
    args = parser.parse_args(argv)

    if args.out.resolve() != SYNTHETIC_DATA_DIR.resolve():
        # Keep copies allowed for tests; still never write fixtures or calls.jsonl.
        pass

    patients, appointments, manifest, logs = build()
    if args.live:
        patients, appointments, live_meta = asyncio.run(enrich_live(patients, appointments))
        manifest["live"] = live_meta
        if not live_meta.get("live"):
            print(f"live enrich skipped: {live_meta.get('reason')}", file=sys.stderr)
        else:
            print(f"live enrich: {live_meta}")

    write_pack(
        patients=patients,
        appointments=appointments,
        manifest=manifest,
        logs=logs,
        out_dir=args.out,
    )
    dest = args.out
    print(f"patients -> {dest / 'patients.json'}")
    print(f"appointments -> {dest / 'appointments.json'}")
    print(f"manifest -> {dest / 'manifest.json'}")
    print(f"logs -> {dest / 'logs'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
