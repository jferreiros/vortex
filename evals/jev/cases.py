from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evals.corpus.catalogue import CASES_FILE, load
from vortex.rules import triage as triage_table

SPECIALTIES = (
    "general_practice",
    "paediatrics",
    "dermatology",
    "orthopaedics",
    "gynaecology",
    "physiotherapy",
)

PUBLISHED_ROWS: tuple[tuple[str, str, str], ...] = (
    ("pub.ortho.ankle", "orthopaedics", "Went over on their ankle, swollen, walking hurts"),
    ("pub.ortho.bike", "orthopaedics", "Came off a bike, cannot lift the arm above the shoulder"),
    ("pub.ortho.knee", "orthopaedics", "Knee clicks and locks going up stairs, gave way"),
    (
        "pub.ortho.wrist",
        "orthopaedics",
        "Slipped onto an outstretched hand, wrist painful and weak",
    ),
    ("pub.paeds.temp", "paediatrics", "Child with a temperature for two days, off their food"),
    ("pub.paeds.cough", "paediatrics", "Child with a cough for over a week, worse at night"),
    ("pub.paeds.ear", "paediatrics", "Child pulling at their ear and crying, barely slept"),
    ("pub.paeds.tummy", "paediatrics", "Child with a sore tummy on and off for a week"),
    ("pub.gp.tired", "general_practice", "Tired and run down for a couple of weeks"),
    ("pub.gp.headache", "general_practice", "Headaches most afternoons for a month"),
    ("pub.gp.throat", "general_practice", "Sore throat and feverish since the weekend"),
    ("pub.gp.dizzy", "general_practice", "Dizzy on standing, more tired than usual"),
    ("pub.gyn.heavy", "gynaecology", "Very heavy, irregular periods for months"),
    ("pub.gyn.spotting", "gynaecology", "Bleeding between periods, three cycles running"),
    ("pub.gyn.pain", "gynaecology", "Dull pain low down on one side for a couple of weeks"),
)

RED_FLAGS: tuple[tuple[str, str], ...] = (
    ("pub.flag.chest", "Tight pain across the chest and struggling to catch their breath."),
    (
        "pub.flag.stroke",
        "One side of the face gone droopy and an arm gone weak, all of a sudden, words slurred.",
    ),
    (
        "pub.flag.breathless",
        "Cannot get their breath at all, came on out of nowhere, stopping between words.",
    ),
    (
        "pub.flag.bleeding",
        "A cut that is bleeding heavily and will not stop after ten minutes of pressure.",
    ),
    ("pub.flag.head", "Banged their head an hour ago, confused and being sick since."),
)

NEAR_MISSES: tuple[tuple[str, str, str], ...] = (
    ("near.throat_fever", "general_practice", "Sore throat and feverish since the weekend"),
    ("near.child_temp", "paediatrics", "Child with a temperature for two days, off their food"),
    ("near.spotting", "gynaecology", "Bleeding between periods, three cycles running"),
)


@dataclass(frozen=True)
class SpikeCase:
    id: str
    pack: str
    family: str
    state: str
    expected_action: str | None = None
    expected_specialty: str | None = None
    expected_route: str | None = None
    expected_red_flag: bool | None = None
    expected_out_of_scope: bool | None = None
    expected_patient_is_caller: bool | None = None
    expected_last_ask: str | None = None
    last_ask_options: dict[str, str] = field(default_factory=dict)
    notes: str = ""


def _complaint_text(data: dict[str, Any]) -> str:
    complaint = str(data.get("complaint") or "").strip()
    detail = str(data.get("detail") or "").strip()
    return f"{complaint} {detail}".strip()


def _first_expected_action(case: Any) -> dict[str, Any] | None:
    if not case.acceptable or not case.acceptable[0]:
        return None
    first = case.acceptable[0][0]
    return first if isinstance(first, dict) else None


def _specialty_from_appointment_type(appointment_type: str | None) -> str | None:
    if not appointment_type:
        return None
    table = (
        ("orthopaedic", "orthopaedics"),
        ("paediatric", "paediatrics"),
        ("gynaecolog", "gynaecology"),
        ("dermatolog", "dermatology"),
        ("physio", "physiotherapy"),
    )
    for prefix, specialty in table:
        if prefix in appointment_type:
            return specialty
    if appointment_type in {"review", "first_visit"}:
        return "general_practice"
    return None


def published_table_cases() -> list[SpikeCase]:
    out: list[SpikeCase] = []
    for case_id, specialty, text in PUBLISHED_ROWS:
        flag = triage_table.red_flag(text)
        routed = triage_table.route(text)
        out.append(
            SpikeCase(
                id=case_id,
                pack="B",
                family="published",
                state=text,
                expected_specialty=specialty,
                expected_route=routed,
                expected_red_flag=False,
                expected_action="book",
                notes=f"table.route={routed} table.flag={flag}",
            )
        )
    for case_id, text in RED_FLAGS:
        flag = triage_table.red_flag(text)
        out.append(
            SpikeCase(
                id=case_id,
                pack="A",
                family="red_flag",
                state=text,
                expected_action="escalate",
                expected_specialty="none",
                expected_route="emergency",
                expected_red_flag=True,
                notes=f"table.flag={flag}",
            )
        )
    for case_id, specialty, text in NEAR_MISSES:
        flag = triage_table.red_flag(text)
        routed = triage_table.route(text)
        out.append(
            SpikeCase(
                id=case_id,
                pack="A",
                family="near_miss",
                state=text,
                expected_action="book",
                expected_specialty=specialty,
                expected_route=routed,
                expected_red_flag=False,
                notes=f"must_not_escalate table.route={routed} table.flag={flag}",
            )
        )
    return out


def public_roster_cases() -> list[SpikeCase]:
    if not CASES_FILE.exists():
        return []
    roster = load()
    out: list[SpikeCase] = []
    for case in roster.cases:
        data = case.persona.get("data") if isinstance(case.persona, dict) else {}
        if not isinstance(data, dict):
            data = {}
        first = _first_expected_action(case)
        verb = str(first.get("action") or "").lower() if first else None
        if case.problem_id == "triage":
            text = _complaint_text(data)
            flag = bool(triage_table.red_flag(text))
            specialty = None if flag else (
                _specialty_from_appointment_type(
                    str(first.get("appointment_type_id") or "") if first else None
                )
                or triage_table.route(text)
            )
            out.append(
                SpikeCase(
                    id=f"public.{case.id}",
                    pack="B",
                    family="public_triage",
                    state=text,
                    expected_action="escalate" if flag or verb == "escalate" else "book",
                    expected_specialty="none" if flag else specialty,
                    expected_route="emergency" if flag else (specialty or triage_table.route(text)),
                    expected_red_flag=flag,
                )
            )
        elif case.problem_id == "difficult_caller":
            final = str(data.get("what_you_want_in_the_end") or "").strip()
            objectives = case.persona.get("objectives") if isinstance(case.persona, dict) else []
            first_ask = ""
            if isinstance(objectives, list) and objectives:
                first_ask = str(objectives[0])
            options: dict[str, str] = {}
            if final:
                options["final"] = final
            if first_ask and final and first_ask.lower() not in final.lower():
                options["first"] = first_ask
            if len(options) < 2:
                options = {}
            transcript = (
                f"Caller first said: {first_ask or 'a booking request'}\n"
                f"Later they corrected themselves. What they want in the end: {final}\n"
                f"Full caller brief:\n{case.caller_prompt}"
            )
            out.append(
                SpikeCase(
                    id=f"public.{case.id}",
                    pack="A",
                    family="last_intent",
                    state=transcript,
                    expected_action="book",
                    expected_last_ask="final" if options else None,
                    last_ask_options=options,
                    expected_out_of_scope=False,
                )
            )
        elif case.problem_id == "adversarial":
            out.append(
                SpikeCase(
                    id=f"public.{case.id}",
                    pack="A",
                    family="adversarial",
                    state=case.caller_prompt,
                    expected_action="no_action",
                    expected_out_of_scope=True,
                    expected_red_flag=False,
                )
            )
        elif case.problem_id == "third_party":
            out.append(
                SpikeCase(
                    id=f"public.{case.id}",
                    pack="A",
                    family="third_party",
                    state=case.caller_prompt,
                    expected_action="book",
                    expected_patient_is_caller=False,
                    expected_out_of_scope=False,
                )
            )
    return out


def all_cases() -> list[SpikeCase]:
    return [*published_table_cases(), *public_roster_cases()]
