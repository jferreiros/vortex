"""A clinic-day of CallLog-shaped calls for the board (today, 19 Sep 2026).

Marta's mix, from the team Discord / WhatsApp notes:

- 15-20% of today's calls are *not* resolved by the agent
- of those, 10% or less were escalated to a doctor; the rest were refused
- every refusal carries a typed ``reason``
- every escalation carries ``reason: medical_emergency``
- today's volume is higher than the previous mock (47)
- two or three calls register new patients

    uv run python -m evals.corpus.clinic_day
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
REPO_ROOT = Path(__file__).resolve().parents[2]

DAY = datetime(2026, 9, 19, tzinfo=MADRID).date()
N_CALLS = 60
N_REGISTER = 3
N_ESCALATE = 1
N_REJECT = 10
N_CANCEL = 4
N_RESCHEDULE = 4
N_BOOK = N_CALLS - N_REGISTER - N_ESCALATE - N_REJECT - N_CANCEL - N_RESCHEDULE

CHECK_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"

SYNTHETIC_DATA_DIR = REPO_ROOT / "synthetic-data"


def dni(digits: int) -> str:
    return f"{digits:08d}{CHECK_LETTERS[digits % 23]}"


# Existing roster patients the public cases already name. BOOK/CANCEL/RESCHEDULE
# look these up; REGISTER callers are *not* in the directory.
PATIENTS: list[dict[str, str]] = [
    {
        "patient_id": "P00001",
        "given_name": "Josefa",
        "first_surname": "Domínguez",
        "second_surname": "Navarro",
        "national_id": "48064716Y",
        "phone": "711330529",
        "insurer": "mapfre",
        "age": "adult",
    },
    {
        "patient_id": "P00004",
        "given_name": "Teresa",
        "first_surname": "López",
        "second_surname": "García",
        "national_id": "60153984Z",
        "phone": "669394942",
        "insurer": "asisa",
        "age": "adult",
    },
    {
        "patient_id": "P00005",
        "given_name": "Ignacio",
        "first_surname": "Vázquez",
        "second_surname": "Moreno",
        "national_id": "65699248R",
        "phone": "731169716",
        "insurer": "cigna",
        "age": "adult",
    },
    {
        "patient_id": "P00008",
        "given_name": "Mario",
        "first_surname": "Delgado",
        "second_surname": "Medina",
        "national_id": "62937630Q",
        "phone": "655913877",
        "insurer": "caser",
        "age": "child",
    },
    {
        "patient_id": "P00009",
        "given_name": "Sonia",
        "first_surname": "Álvarez",
        "second_surname": "Medina",
        "national_id": "62819257R",
        "phone": "746987792",
        "insurer": "privado",
        "age": "child",
    },
    {
        "patient_id": "P00011",
        "given_name": "Chloe",
        "first_surname": "Roberts",
        "second_surname": "Smith",
        "national_id": "Z4237244M",
        "phone": "708729566",
        "insurer": "mapfre",
        "age": "adult",
    },
    {
        "patient_id": "P00012",
        "given_name": "Amelia",
        "first_surname": "Hughes",
        "second_surname": "White",
        "national_id": "13309713G",
        "phone": "712676131",
        "insurer": "sanitas",
        "age": "adult",
    },
    {
        "patient_id": "P00015",
        "given_name": "Josefa",
        "first_surname": "Sánchez",
        "second_surname": "Gutiérrez",
        "national_id": "49526979K",
        "phone": "755842366",
        "insurer": "adeslas",
        "age": "adult",
    },
]

NEW_PATIENTS: list[dict[str, str]] = [
    {
        "given_name": "Laura",
        "first_surname": "Peña",
        "second_surname": "Soler",
        "national_id": dni(47281930),
        "date_of_birth": "1987-04-12",
        "phone": "612448901",
        "email": "laura.pena.soler@gmail.com",
        "insurer": "sanitas",
    },
    {
        "given_name": "Marc",
        "first_surname": "Vila",
        "second_surname": "Costa",
        "national_id": dni(58392014),
        "date_of_birth": "1994-11-03",
        "phone": "634771208",
        "email": "marc.vila.costa@outlook.com",
        "insurer": "mapfre",
    },
    {
        "given_name": "Ainhoa",
        "first_surname": "Ruiz",
        "second_surname": "Etxeberria",
        "national_id": dni(61029387),
        "date_of_birth": "2001-07-22",
        "phone": "699120447",
        "email": "ainhoa.ruiz.e@icloud.com",
        "insurer": "asisa",
    },
]

# (provider_id, location_id, appointment_type_id, spoken name, slot hour, slot minute)
BOOK_ROTATION: list[tuple[str, str, str, str, int, int]] = [
    ("PR01", "centro", "review", "Dra. Ortiz", 9, 0),
    ("PR02", "norte", "first_visit", "Dr. Sáez", 10, 15),
    ("PR04", "centro", "dermatology_review", "Dra. Iglesias", 11, 30),
    ("PR05", "sur", "first_visit", "Dr. Iglesia", 12, 0),
    ("PR06", "sur", "review", "D. Álvaro Cid", 16, 45),
    ("PR01", "centro", "first_visit", "Dra. Ortiz", 17, 15),
]

CHILD_BOOK = ("PR03", "centro", "paediatric_review", "Dra. Sáenz", 10, 0)

# One typed reason per refusal. Two share no_availability so the insights
# page has a dominant bucket without inventing a reason.
REJECTIONS: list[tuple[str, str]] = [
    ("no_availability", "No hay hueco en la franja que piden."),
    ("no_availability", "La agenda de esa semana está llena."),
    ("referral_required", "Dermato pide volante y no lo tiene en ficha."),
    ("specialty_not_covered", "El plan no cubre ginecología aquí."),
    ("provider_not_found", "El apellido que dicta no coincide con nadie."),
    ("clinic_closed", "Piden domingo por la mañana: el centro no abre."),
    ("not_eligible_age", "Pediatría no admite a un adulto."),
    ("location_hours", "Sur cierra a las 14:00 los viernes; piden las 18:00."),
    ("out_of_scope", "Quiere consejo médico, no una cita."),
    ("provider_on_leave", "Piden al Dr. Requena, de baja hasta el 30."),
]

APPOINTMENTS: list[tuple[str, str, str]] = [
    ("A000645", "P00001", "PR05"),
    ("A001101", "P00005", "PR01"),
    ("A001335", "P00012", "PR01"),
    ("A001498", "P00011", "PR02"),
    ("A001601", "P00004", "PR05"),
    ("A001727", "P00015", "PR06"),
]


def _iso(stamp: datetime) -> str:
    return stamp.isoformat()


def _full_name(person: dict[str, str]) -> str:
    return " ".join(
        p
        for p in (
            person.get("given_name"),
            person.get("first_surname"),
            person.get("second_surname"),
        )
        if p
    )


def _call_id(seq: int) -> str:
    return f"clinic-day-{DAY.isoformat()}-{seq:03d}"


def _event(ts: datetime, call_id: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {"ts": _iso(ts), "call_id": call_id, "kind": kind, **extra}


def _emit(
    *,
    seq: int,
    start: datetime,
    duration_s: int,
    phone: str,
    user: str,
    assistant: str,
    tools: list[tuple[str, dict[str, Any], dict[str, Any]]],
    action: dict[str, Any],
    extra_started: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    call_id = _call_id(seq)
    t0 = start
    t1 = start + timedelta(seconds=8)
    t2 = start + timedelta(seconds=18)
    end = start + timedelta(seconds=duration_s)
    route = {
        "REGISTER": "register",
        "BOOK": "book",
        "RESCHEDULE": "reschedule",
        "CANCEL": "cancel",
        "NO_ACTION": "no-action",
        "ESCALATE": "escalate",
    }[str(action["action"])]
    events = [
        _event(
            t0,
            call_id,
            "call.started",
            from_number=phone,
            problem_id="clinic_day",
            language="es",
            clinic="synthetic-data",
            voice="synthetic",
            source="clinic_day",
            **(extra_started or {}),
        ),
        _event(t1, call_id, "turn.user", text=user),
        _event(t2, call_id, "turn.assistant", text=assistant),
    ]
    cursor = t2
    for name, args, result in tools:
        cursor += timedelta(seconds=4)
        events.append(_event(cursor, call_id, "tool.called", tool=name, args=args))
        cursor += timedelta(seconds=3)
        events.append(
            _event(
                cursor,
                call_id,
                "tool.returned",
                tool=name,
                result=result,
                ms=180 + seq * 3,
            )
        )
    events.append(
        _event(
            end - timedelta(seconds=4),
            call_id,
            "submit.result",
            route=route,
            payload=action,
            result={"status": "accepted", "synthetic": True},
        )
    )
    events.append(_event(end, call_id, "call.ended", reason="synthetic-clinic-day"))
    events.append(
        _event(
            end,
            call_id,
            "call.summary",
            turns=2,
            tools=len(tools),
            actions=[action],
            problem_id="clinic_day",
            shape=_shape(action),
            duration_ms=duration_s * 1000,
            source="clinic_day",
        )
    )
    return events


def _shape(action: dict[str, Any]) -> str:
    verb = str(action.get("action", ""))
    reason = action.get("reason")
    return f"{verb}({reason})" if reason else verb


def _starts() -> list[datetime]:
    """Sixty arrivals across the open line, 08:12 → 19:21 Europe/Madrid."""
    origin = datetime(2026, 9, 19, 8, 12, tzinfo=MADRID)
    return [origin + timedelta(minutes=11 * i + (i % 3)) for i in range(N_CALLS)]


def _duration(seq: int) -> int:
    return 55 + (seq * 11) % 90


def _patient_match(person: dict[str, str]) -> dict[str, Any]:
    return {
        "patient": {
            "patient_id": person["patient_id"],
            "full_name": _full_name(person),
            "given_name": person["given_name"],
            "first_surname": person["first_surname"],
            "second_surname": person["second_surname"],
            "national_id": person["national_id"],
            "phone": person["phone"],
            "insurer": person["insurer"],
        },
        "matches": 1,
    }


def _book_spec(person: dict[str, str], index: int) -> tuple[str, str, str, str, int, int]:
    if person.get("age") == "child":
        return CHILD_BOOK
    return BOOK_ROTATION[index % len(BOOK_ROTATION)]


def _slot(day_offset: int, hour: int, minute: int) -> str:
    stamp = datetime(2026, 9, 21, hour, minute, tzinfo=MADRID) + timedelta(days=day_offset)
    return stamp.isoformat()


def _book_call(
    seq: int, start: datetime, person: dict[str, str], index: int
) -> list[dict[str, Any]]:
    provider_id, location_id, appt_type, doctor, hour, minute = _book_spec(person, index)
    slot = _slot(index % 5, hour, minute)
    name = _full_name(person)
    action = {
        "action": "BOOK",
        "patient_id": person["patient_id"],
        "provider_id": provider_id,
        "location_id": location_id,
        "appointment_type_id": appt_type,
        "slot": slot,
        "policy_id": person["insurer"] or "privado",
    }
    tools = [
        (
            "find_patient",
            {"name": name, "national_id": person["national_id"]},
            _patient_match(person),
        ),
        (
            "find_slots",
            {
                "date_from": slot[:10],
                "date_to": slot[:10],
                "time_from": f"{hour:02d}:{minute:02d}",
                "provider_id": provider_id,
                "location_id": location_id,
            },
            {
                "slots": [
                    {
                        "start": slot,
                        "provider_id": provider_id,
                        "location_id": location_id,
                        "appointment_type_id": appt_type,
                        "provider": {"name": doctor, "id": provider_id},
                    }
                ]
            },
        ),
        (
            "prepare_booking",
            {"patient_id": person["patient_id"], "slot": slot},
            {"kind": "book", **{k: v for k, v in action.items() if k != "action"}},
        ),
    ]
    user = (
        f"Hola, soy {name}. Quería una cita con {doctor}, "
        f"el lunes a las {hour}:{minute:02d} me iría bien."
    )
    assistant = (
        f"Claro, {person['given_name']}. Tengo un hueco con {doctor} "
        f"el {slot[8:10]} de septiembre a las {hour}:{minute:02d}. Lo dejo anotado."
    )
    return _emit(
        seq=seq,
        start=start,
        duration_s=_duration(seq),
        phone=person["phone"],
        user=user,
        assistant=assistant,
        tools=tools,
        action=action,
    )


def _register_call(seq: int, start: datetime, newbie: dict[str, str]) -> list[dict[str, Any]]:
    name = _full_name(newbie)
    action = {
        "action": "REGISTER",
        "new_patient": {
            "given_name": newbie["given_name"],
            "first_surname": newbie["first_surname"],
            "second_surname": newbie["second_surname"],
            "national_id": newbie["national_id"],
            "date_of_birth": newbie["date_of_birth"],
            "phone": newbie["phone"],
            "email": newbie["email"],
            "insurer": newbie["insurer"],
        },
    }
    tools = [
        (
            "find_patient",
            {"name": name, "national_id": newbie["national_id"]},
            {"patient": None, "matches": 0},
        ),
        (
            "prepare_registration",
            {"national_id": newbie["national_id"]},
            {"kind": "register", "new_patient": action["new_patient"]},
        ),
    ]
    user = (
        f"Buenos días, me llamo {name}, DNI {newbie['national_id']}. "
        "No he venido nunca y quiero darme de alta, ahora no pido cita."
    )
    assistant = (
        f"De acuerdo, {newbie['given_name']}. No está en el directorio; "
        "registro los datos y no dejo ninguna cita hoy."
    )
    return _emit(
        seq=seq,
        start=start,
        duration_s=_duration(seq),
        phone=newbie["phone"],
        user=user,
        assistant=assistant,
        tools=tools,
        action=action,
        extra_started={"new_patient": True},
    )


def _reject_call(
    seq: int, start: datetime, person: dict[str, str], reason: str, why: str
) -> list[dict[str, Any]]:
    name = _full_name(person)
    action = {"action": "NO_ACTION", "reason": reason}
    tools = [
        (
            "find_patient",
            {"name": name, "national_id": person["national_id"]},
            _patient_match(person),
        ),
        (
            "check_eligibility",
            {"patient_id": person["patient_id"]},
            {"kind": "no-action", "reason": reason, "rejection": {"reason": reason}},
        ),
    ]
    user = f"Soy {name}. {why} ¿Me pueden dar cita igual?"
    assistant = (
        f"Lo siento, {person['given_name']}: no puedo completar la petición. "
        "El motivo queda registrado."
    )
    return _emit(
        seq=seq,
        start=start,
        duration_s=_duration(seq),
        phone=person["phone"],
        user=user,
        assistant=assistant,
        tools=tools,
        action=action,
    )


def _escalate_call(seq: int, start: datetime, person: dict[str, str]) -> list[dict[str, Any]]:
    name = _full_name(person)
    action = {"action": "ESCALATE", "reason": "medical_emergency"}
    tools = [
        (
            "find_patient",
            {"name": name, "national_id": person["national_id"]},
            _patient_match(person),
        ),
        (
            "triage",
            {"complaint": "dolor en el pecho y falta de aire"},
            {
                "kind": "escalate",
                "reason": "medical_emergency",
                "rejection": {"reason": "medical_emergency"},
            },
        ),
    ]
    user = (
        f"Soy {name}. Tengo un dolor fuerte en el pecho, me falta el aire "
        "y se me va el brazo izquierdo. ¿Me dan cita ya?"
    )
    assistant = (
        "Esto no es una cita: es una urgencia. Traslado la llamada a un médico y no reservo nada."
    )
    return _emit(
        seq=seq,
        start=start,
        duration_s=_duration(seq),
        phone=person["phone"],
        user=user,
        assistant=assistant,
        tools=tools,
        action=action,
    )


def _cancel_call(
    seq: int, start: datetime, person: dict[str, str], appointment_id: str, provider_id: str
) -> list[dict[str, Any]]:
    name = _full_name(person)
    action = {"action": "CANCEL", "appointment_id": appointment_id}
    slot = "2026-09-28T12:30:00+02:00"
    tools = [
        (
            "find_patient",
            {"name": name, "national_id": person["national_id"]},
            _patient_match(person),
        ),
        (
            "list_appointments",
            {"patient_id": person["patient_id"], "when": "upcoming"},
            {
                "appointments": [
                    {
                        "appointment_id": appointment_id,
                        "patient_id": person["patient_id"],
                        "provider_id": provider_id,
                        "start": slot,
                    }
                ]
            },
        ),
    ]
    user = f"Soy {name}. Quiero cancelar mi próxima cita, la {appointment_id}."
    assistant = f"Hecho, {person['given_name']}: cancelo esa cita y dejo el hueco libre."
    return _emit(
        seq=seq,
        start=start,
        duration_s=_duration(seq),
        phone=person["phone"],
        user=user,
        assistant=assistant,
        tools=tools,
        action=action,
    )


def _reschedule_call(
    seq: int, start: datetime, person: dict[str, str], appointment_id: str, provider_id: str
) -> list[dict[str, Any]]:
    name = _full_name(person)
    slot = _slot(3, 11, 0)
    action = {
        "action": "RESCHEDULE",
        "appointment_id": appointment_id,
        "provider_id": provider_id,
        "location_id": "centro",
        "slot": slot,
        "policy_id": person["insurer"] or "privado",
    }
    tools = [
        (
            "find_patient",
            {"name": name, "national_id": person["national_id"]},
            _patient_match(person),
        ),
        (
            "list_appointments",
            {"patient_id": person["patient_id"], "when": "upcoming"},
            {
                "appointments": [
                    {
                        "appointment_id": appointment_id,
                        "patient_id": person["patient_id"],
                        "provider_id": provider_id,
                        "start": "2026-09-28T09:00:00+02:00",
                    }
                ]
            },
        ),
        (
            "prepare_reschedule",
            {"appointment_id": appointment_id, "slot": slot},
            {"kind": "reschedule", **{k: v for k, v in action.items() if k != "action"}},
        ),
    ]
    user = f"Soy {name}. Quiero mover mi cita {appointment_id} a más tarde esta semana."
    assistant = f"La paso al {slot[8:10]} a las 11:00, {person['given_name']}. Mismo médico."
    return _emit(
        seq=seq,
        start=start,
        duration_s=_duration(seq),
        phone=person["phone"],
        user=user,
        assistant=assistant,
        tools=tools,
        action=action,
    )


def build_clinic_day_events() -> list[dict[str, Any]]:
    """Sixty CallLog events for 19 Sep 2026, oldest first."""
    starts = _starts()
    events: list[dict[str, Any]] = []
    seq = 1

    def take_start() -> datetime:
        nonlocal seq
        stamp = starts[seq - 1]
        return stamp

    for newbie in NEW_PATIENTS:
        events.extend(_register_call(seq, take_start(), newbie))
        seq += 1

    person = PATIENTS[0]
    events.extend(_escalate_call(seq, take_start(), person))
    seq += 1

    for i, (reason, why) in enumerate(REJECTIONS):
        events.extend(
            _reject_call(seq, take_start(), PATIENTS[(i + 1) % len(PATIENTS)], reason, why)
        )
        seq += 1

    for i in range(N_CANCEL):
        appt_id, pid, provider_id = APPOINTMENTS[i % len(APPOINTMENTS)]
        holder = next((p for p in PATIENTS if p["patient_id"] == pid), PATIENTS[i % len(PATIENTS)])
        events.extend(_cancel_call(seq, take_start(), holder, appt_id, provider_id))
        seq += 1

    for i in range(N_RESCHEDULE):
        appt_id, pid, provider_id = APPOINTMENTS[(i + 2) % len(APPOINTMENTS)]
        holder = next((p for p in PATIENTS if p["patient_id"] == pid), PATIENTS[i % len(PATIENTS)])
        events.extend(_reschedule_call(seq, take_start(), holder, appt_id, provider_id))
        seq += 1

    for i in range(N_BOOK):
        events.extend(_book_call(seq, take_start(), PATIENTS[i % len(PATIENTS)], i))
        seq += 1

    return events


def mix_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts and percentages the dashboard asserts against."""
    verbs: dict[str, int] = {}
    reasons: dict[str, int] = {}
    n_calls = 0
    for event in events:
        if event.get("kind") != "call.summary":
            continue
        n_calls += 1
        actions = event.get("actions") or []
        last = actions[-1] if actions else {}
        verb = str(last.get("action") or "")
        verbs[verb] = verbs.get(verb, 0) + 1
        if last.get("reason"):
            reason = str(last["reason"])
            reasons[reason] = reasons.get(reason, 0) + 1
    resolved = sum(verbs.get(v, 0) for v in ("BOOK", "REGISTER", "RESCHEDULE", "CANCEL"))
    rejected = verbs.get("NO_ACTION", 0)
    escalated = verbs.get("ESCALATE", 0)
    unresolved = rejected + escalated
    return {
        "day": DAY.isoformat(),
        "calls": n_calls,
        "verbs": verbs,
        "reasons": reasons,
        "resolved": resolved,
        "rejected": rejected,
        "escalated": escalated,
        "unresolved": unresolved,
        "unresolved_pct": round(100 * unresolved / n_calls, 1) if n_calls else 0.0,
        "resolved_pct": round(100 * resolved / n_calls, 1) if n_calls else 0.0,
        "escalated_share_of_unresolved_pct": (
            round(100 * escalated / unresolved, 1) if unresolved else 0.0
        ),
        "new_patients": verbs.get("REGISTER", 0),
    }


def write_clinic_day(out_dir: Path = SYNTHETIC_DATA_DIR) -> Path:
    events = build_clinic_day_events()
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / "clinic_day.jsonl"
    lines = [json.dumps(event, ensure_ascii=False, default=str) for event in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    path = write_clinic_day()
    stats = mix_from_events(build_clinic_day_events())
    print(f"wrote {path}")
    print(
        f"  calls {stats['calls']}  resolved {stats['resolved_pct']}%  "
        f"unresolved {stats['unresolved_pct']}%  "
        f"escalate/unresolved {stats['escalated_share_of_unresolved_pct']}%  "
        f"register {stats['new_patients']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
