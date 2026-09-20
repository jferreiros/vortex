"""Seed ~50 fictitious, complete calls into Supabase for the wall demo.

    uv run python database/scripts/seed_fake_history.py
    uv run python database/scripts/seed_fake_history.py --count 60 --dry-run

Writes three things per call, the same shape the real line writes at hangup:

- ``public.call_events`` — a short synthetic transcript (``call.started``,
  a few ``turn.*``, ``tool.*``, ``submit.*``, ``call.ended``,
  ``call.summary``) so the live view and call feed have something to open.
- ``public.calls`` — one row per call (``database.db.insert_call``).
- ``public.appointments`` — one row per booked/reschescheduled slot
  (``database.db.insert_appointment``).

Every id is invented and every call_id is prefixed ``SEED-`` so this can
never collide with a real Twilio callSid or a scored run. Re-running is
mostly safe: ``calls``/``appointments`` upsert on their primary key and
``call_events`` dedupes on ``event_hash`` — only the *set* of rows grows if
you ask for more than last time.

Goes over PostgREST (``database.remote`` / ``database.db``), the same path
the line and the board use at runtime. Needs ``SUPABASE_URL`` and
``SUPABASE_SERVICE_ROLE_KEY`` (or ``SUPABASE_SECRET_KEY``) in the
environment or ``.env`` — no direct Postgres connection required.
"""

from __future__ import annotations

import argparse
import itertools
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from database import db, remote  # noqa: E402
from vortex.clinic.fixtures import PATIENTS, PROVIDERS  # noqa: E402

TZ = "+02:00"  # Europe/Madrid, CEST — every date this script uses is in September.

#: "Today" the whole seed clusters around. Matches the environment's own
#: clock at the time this script was written; change it if you run this
#: script much later and want the cluster to follow.
TODAY = date(2026, 9, 20)

DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def dni_letter(digits: str) -> str:
    return DNI_LETTERS[int(digits) % 23]


# ---------------------------------------------------------------------------
# clinic data, reshaped from vortex/clinic/fixtures.py for quick lookup
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provider:
    provider_id: str
    name: str
    specialty_id: str
    specialty_name: str
    site_id: str
    site_name: str
    refuses: tuple[str, ...]


SITE_NAME = {"centro": "Arenal Centro", "norte": "Arenal Norte", "sur": "Arenal Sur"}

APPT_TYPE_NAME = {
    "first_visit": "First visit",
    "review": "Review",
    "dermatology_first": "Dermatology first visit",
    "dermatology_review": "Dermatology review",
}

# Dr. Requena (PR07) is on leave 2026-09-14 to 2026-09-30 in the fixtures —
# excluded from the bookable pool so the seed data does not contradict its
# own clinic, and used once on purpose for a provider_on_leave no_action.
PROVIDER_BY_ID = {
    p["id"]: Provider(
        provider_id=p["id"],
        name=p["name"],
        specialty_id=p["specialty_id"],
        specialty_name=p["specialty_name"],
        site_id=next(k for k, v in SITE_NAME.items() if v in p["location_names"]),
        site_name=p["location_names"][0],
        refuses=tuple(r["id"] for r in p["refused_insurers"]),
    )
    for p in PROVIDERS
}
REQUENA = PROVIDER_BY_ID["PR07"]
BOOKABLE_PROVIDERS = [p for p in PROVIDER_BY_ID.values() if p.provider_id != "PR07"]

PATIENT_BY_ID = {p["patient_id"]: p for p in PATIENTS}
#: Adult, nameable patients — leave the two children (P00107, P00204) out of
#: the general pool; they show up only in the third-party-style calls below.
ADULT_PATIENT_IDS = [
    pid
    for pid, p in PATIENT_BY_ID.items()
    if pid not in {"P00107", "P00204"}
]

INSURERS = [
    "sanitas", "adeslas", "dkv", "asisa", "mapfre",
    "caser", "cigna", "axa", "nueva_mutua", "privado",
]

#: Brand-new callers for the register scenarios — never in PATIENTS, so the
#: directory genuinely would not know them.
NEW_CALLERS = [
    {
        "patient_id": "P00601",
        "given_name": "Beatriz", "first_surname": "Cano", "second_surname": "Reyes",
        "dob": "1988-02-11", "insurer": "sanitas",
    },
    {
        "patient_id": "P00602",
        "given_name": "Diego", "first_surname": "Serrano", "second_surname": "Blanco",
        "dob": "1975-07-23", "insurer": "adeslas",
    },
    {
        "patient_id": "P00603",
        "given_name": "Nuria", "first_surname": "Campos", "second_surname": "Iglesias",
        "dob": "1999-12-30", "insurer": "asisa",
    },
    {
        "patient_id": "P00604",
        "given_name": "Hugo", "first_surname": "Marín", "second_surname": "Aguilar",
        "dob": "1963-04-17", "insurer": "dkv",
    },
    {
        "patient_id": "P00605",
        "given_name": "Paula", "first_surname": "Bravo", "second_surname": "Nieto",
        "dob": "1991-10-05", "insurer": "cigna",
    },
    {
        "patient_id": "P00606",
        "given_name": "Álvaro", "first_surname": "Gil", "second_surname": "Pascual",
        "dob": "1982-09-19", "insurer": "axa",
    },
    {
        "patient_id": "P00607",
        "given_name": "Lucía", "first_surname": "Domínguez", "second_surname": "Ferrer",
        "dob": "1994-01-27", "insurer": "sanitas",
    },
    {
        "patient_id": "P00608",
        "given_name": "Javier", "first_surname": "Ortega", "second_surname": "Camacho",
        "dob": "1970-05-03", "insurer": "mapfre",
    },
    {
        "patient_id": "P00609",
        "given_name": "Marina", "first_surname": "Vega", "second_surname": "Cortés",
        "dob": "1987-12-14", "insurer": "nueva_mutua",
    },
    {
        "patient_id": "P00610",
        "given_name": "Sergio", "first_surname": "Peña", "second_surname": "Redondo",
        "dob": "1959-08-22", "insurer": "caser",
    },
    {
        "patient_id": "P00611",
        "given_name": "Alba", "first_surname": "Lozano", "second_surname": "Suárez",
        "dob": "1996-03-08", "insurer": "privado",
    },
    {
        "patient_id": "P00612",
        "given_name": "Iván", "first_surname": "Cabrera", "second_surname": "Reina",
        "dob": "1977-11-30", "insurer": "adeslas",
    },
    {
        "patient_id": "P00613",
        "given_name": "Sara", "first_surname": "Montero", "second_surname": "Vidal",
        "dob": "1992-06-17", "insurer": "asisa",
    },
]


def full_name(p: dict[str, Any]) -> str:
    return f"{p['given_name']} {p['first_surname']} {p['second_surname']}".strip()


def patient_ref(patient_id: str, p: dict[str, Any]) -> dict[str, Any]:
    """The ``{"patient": {...}}`` shape ``view.build_call`` reads a caller's
    name and id off of (``_patient_name``/``_patient_id``) — every
    identifying tool call must nest its match under this key or the Live
    feed card never learns who called."""
    return {
        "patient_id": patient_id,
        "given_name": p["given_name"],
        "first_surname": p["first_surname"],
        "second_surname": p["second_surname"],
    }


def slot_ref(slot: datetime, provider: Provider, appt_type_id: str) -> dict[str, Any]:
    """The ``{"slots": [...]}`` shape ``view.build_call`` reads a card's
    provider and slot off of (``_provider_name``/``_slot_label``)."""
    return {
        "slots": [
            {
                "start": iso(slot),
                "appointment_type": appt_type_id,
                "provider": {"provider_id": provider.provider_id, "name": provider.name},
                "location_id": provider.site_id,
            }
        ]
    }


def appointment_type_for(provider: Provider, new_patient: bool) -> tuple[str, str]:
    if provider.specialty_id == "dermatology":
        return ("dermatology_first", "Dermatology first visit") if new_patient else (
            "dermatology_review", "Dermatology review"
        )
    return ("first_visit", "First visit") if new_patient else ("review", "Review")


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------


def clinic_days(start: date, end: date, *, allow_sundays: bool = False) -> list[date]:
    """Every day in [start, end]. Sundays are dropped by default — the
    clinic answers no calls on one — but a deliberately dense "concentrate
    on the last day or two" pass (``--window-days`` small, ``--allow-
    sundays`` set) wants today included even when today is one."""
    days: list[date] = []
    cur = start
    while cur <= end:
        if allow_sundays or cur.weekday() != 6:  # 6 = Sunday
            days.append(cur)
        cur += timedelta(days=1)
    return days


def random_call_time(d: date, rng: random.Random) -> datetime:
    """A plausible moment a call landed on ``d``. Weekdays stay inside
    opening hours (09:00-19:00); a weekend day spreads 08:00-21:00 — when
    the whole deck is deliberately concentrated on the last day or two for a
    demo (a Saturday/Sunday), that is "all day", not "the Saturday morning
    slice a real appointment would respect"."""
    if d.weekday() >= 5:  # Saturday or Sunday
        hour = rng.randint(8, 21)
    else:
        hour = rng.randint(9, 19)
    minute = rng.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
    return datetime.combine(d, datetime.min.time()).replace(hour=hour, minute=minute)


def random_slot(
    after: date, provider: Provider, rng: random.Random, span_days: int = 14
) -> datetime:
    """A booked slot for ``provider``, at least one day after ``after`` (never
    same-day), inside the site's own hours."""
    for _ in range(30):
        d = after + timedelta(days=rng.randint(1, span_days))
        if d.weekday() == 6:
            continue
        if provider.site_id == "sur" and d.weekday() == 4:  # Sur: Friday 09:00-14:00
            hour_max, minute_max = 13, 45
        elif d.weekday() == 5:  # every site: Saturday 09:00-14:00 (Centro only, but fine for demo)
            hour_max, minute_max = 13, 45
        else:
            hour_max, minute_max = 19, 45
        hour = rng.randint(9, hour_max)
        minute = (
            rng.choice([0, 15, 30, 45])
            if hour < hour_max
            else rng.choice([0, 15, 30, minute_max])
        )
        return datetime.combine(d, datetime.min.time()).replace(hour=hour, minute=minute)
    # Fallback: a safe Tuesday morning a week out.
    d = after + timedelta(days=7)
    return datetime.combine(d, datetime.min.time()).replace(hour=10, minute=0)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + TZ


def appointment_status(slot: datetime, rng: random.Random) -> str:
    slot_date = slot.date()
    if slot_date < TODAY:
        return rng.choices(["completed", "no_show"], weights=[9, 1])[0]
    if slot_date == TODAY:
        return "confirmed"
    return "scheduled"


# ---------------------------------------------------------------------------
# transcript templates — short, plausible, per outcome
# ---------------------------------------------------------------------------


def base_events(call_id: str, started: datetime, from_number: str) -> list[dict[str, Any]]:
    return [
        {"ts": started, "call_id": call_id, "kind": "call.started",
         "stream_sid": f"MZ{uuid4().hex[:20]}", "from_number": from_number,
         # Real keys: vortex.line.session logs Settings.describe()'s own
         # "voice"/"clinic" here — view.build_call reads exactly these two,
         # not "voice_mode"/"clinic_mode".
         "voice": "pipecat", "clinic": "live"},
    ]


def turn(call_id: str, ts: datetime, who: str, text: str) -> dict[str, Any]:
    return {"ts": ts, "call_id": call_id, "kind": f"turn.{who}", "text": text}


def tool_pair(
    call_id: str, ts: datetime, tool: str, args: dict[str, Any], result: Any
) -> list[dict[str, Any]]:
    return [
        {"ts": ts, "call_id": call_id, "kind": "tool.called", "tool": tool, "args": args},
        {
            "ts": ts + timedelta(milliseconds=350),
            "call_id": call_id,
            "kind": "tool.returned",
            "tool": tool,
            "result": result,
            "ms": 340.0 + random.random() * 80,
        },
    ]


def submit_events(
    call_id: str, ts: datetime, route: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    return [
        {"ts": ts, "call_id": call_id, "kind": "submit.sent", "route": route, "payload": payload},
        {
            "ts": ts + timedelta(milliseconds=180),
            "call_id": call_id,
            "kind": "submit.result",
            "route": route,
            "payload": payload,
            "result": {"status": "accepted", "http_status": 200},
        },
    ]


def closing_events(
    call_id: str,
    ts: datetime,
    turns: int,
    tools: int,
    actions: list[dict[str, Any]],
    duration_ms: int,
) -> list[dict[str, Any]]:
    return [
        {"ts": ts, "call_id": call_id, "kind": "call.ended", "reason": "caller_hangup",
         "media_frames_in": duration_ms // 20, "media_frames_out": duration_ms // 20},
        {"ts": ts + timedelta(milliseconds=50), "call_id": call_id, "kind": "call.summary",
         "turns": turns, "tools": tools, "actions": actions, "duration_ms": duration_ms},
    ]


# ---------------------------------------------------------------------------
# one call per scenario kind
# ---------------------------------------------------------------------------


@dataclass
class SeedCall:
    call_id: str
    events: list[dict[str, Any]]
    calls_row: dict[str, Any]
    appointment_row: dict[str, Any] | None


def make_book_call(rng: random.Random, call_date: date) -> SeedCall:
    patient_id = rng.choice(ADULT_PATIENT_IDS)
    patient = PATIENT_BY_ID[patient_id]
    candidates = [p for p in BOOKABLE_PROVIDERS if p.provider_id not in patient["refused"]]
    provider = rng.choice(candidates)
    started = random_call_time(call_date, rng)
    call_id = f"SEED-book-{uuid4().hex[:12]}"
    new_patient = not patient["has_visited_before"]
    appt_type_id, appt_type_name = appointment_type_for(provider, new_patient)
    slot = random_slot(call_date, provider, rng)
    slot_end = slot + timedelta(minutes=15 if appt_type_id.endswith("review") else 30)

    events = base_events(call_id, started, patient["phone_display"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Hola, soy {full_name(patient)}, quería pedir cita con {provider.name}."))
    t += timedelta(seconds=4)
    events.append(turn(call_id, t, "assistant",
        f"Claro, {patient['given_name']}, un momento que le confirmo los datos."))
    t += timedelta(seconds=2)
    events.extend(tool_pair(call_id, t, "lookup_patient", {"query": full_name(patient)},
        {"patient": patient_ref(patient_id, patient), "matched_fields": ["name"]}))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "assistant",
        f"Tengo un hueco el {slot.strftime('%d/%m')} a las {slot.strftime('%H:%M')} "
        f"en {provider.site_name}, ¿le viene bien?"))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "user", "Sí, perfecto, resérvemelo."))
    t += timedelta(seconds=2)
    events.extend(tool_pair(call_id, t, "check_availability",
        {"provider_id": provider.provider_id, "appointment_type_id": appt_type_id},
        slot_ref(slot, provider, appt_type_id)))
    t += timedelta(seconds=2)
    payload = {
        "call_id": call_id, "patient_id": patient_id, "provider_id": provider.provider_id,
        "location_id": provider.site_id, "appointment_type_id": appt_type_id,
        "slot": iso(slot), "policy_id": patient["insurer"],
    }
    events.extend(submit_events(call_id, t, "book", payload))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant", "Listo, cita confirmada. ¡Que vaya bien!"))
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=5, tools=2,
        actions=[{"route": "book", "payload": payload}], duration_ms=duration_ms))

    appt_id = f"LCL-{uuid4().hex[:16]}"
    status = appointment_status(slot, rng)
    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="booking",
            language="es", from_number=patient["phone_display"],
            started_at=iso(started), duration_ms=duration_ms, outcome="book",
        ),
        appointment_row=dict(
            id=appt_id, status=status, patient_id=patient_id,
            patient_name=full_name(patient), patient_phone=patient["phone_display"],
            patient_email=None, provider_id=provider.provider_id, provider_name=provider.name,
            specialty_id=provider.specialty_id, specialty_name=provider.specialty_name,
            site_id=provider.site_id, site_name=provider.site_name,
            slot_start=iso(slot), slot_end=iso(slot_end), insurer=patient["insurer"],
            appointment_type_id=appt_type_id, appointment_type_name=appt_type_name,
            reason=f"Cita con {provider.name}.",
        ),
    )


def make_reschedule_call(rng: random.Random, call_date: date) -> SeedCall:
    patient_id = rng.choice(ADULT_PATIENT_IDS)
    patient = PATIENT_BY_ID[patient_id]
    candidates = [p for p in BOOKABLE_PROVIDERS if p.provider_id not in patient["refused"]]
    provider = rng.choice(candidates)
    started = random_call_time(call_date, rng)
    call_id = f"SEED-resch-{uuid4().hex[:12]}"
    new_patient = not patient["has_visited_before"]
    appt_type_id, appt_type_name = appointment_type_for(provider, new_patient)
    old_slot = random_slot(call_date, provider, rng, span_days=5)
    new_slot = random_slot(call_date, provider, rng, span_days=14)
    slot_end = new_slot + timedelta(minutes=15 if appt_type_id.endswith("review") else 30)
    appt_id = f"A{uuid4().hex[:8].upper()}"

    events = base_events(call_id, started, patient["phone_display"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Hola, soy {full_name(patient)}. Tengo cita con {provider.name} el "
        f"{old_slot.strftime('%d/%m')} y necesito cambiarla."))
    t += timedelta(seconds=4)
    events.extend(tool_pair(call_id, t, "list_appointments", {"patient_id": patient_id},
        {
            "patient": patient_ref(patient_id, patient),
            "appointments": [{"appointment_id": appt_id, "start_time": iso(old_slot)}],
        }))
    t += timedelta(seconds=3)
    events.extend(tool_pair(call_id, t, "check_availability",
        {"provider_id": provider.provider_id, "appointment_type_id": appt_type_id},
        slot_ref(new_slot, provider, appt_type_id)))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant",
        f"Le puedo ofrecer el {new_slot.strftime('%d/%m')} a las {new_slot.strftime('%H:%M')}, "
        "¿se la muevo a esa hora?"))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "user", "Sí, esa hora me viene mejor."))
    t += timedelta(seconds=2)
    payload = {
        "call_id": call_id, "appointment_id": appt_id, "provider_id": provider.provider_id,
        "location_id": provider.site_id, "slot": iso(new_slot), "policy_id": patient["insurer"],
    }
    events.extend(submit_events(call_id, t, "reschedule", payload))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant", "Perfecto, ha quedado movida. Gracias por avisar."))
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=4, tools=2,
        actions=[{"route": "reschedule", "payload": payload}], duration_ms=duration_ms))

    status = appointment_status(new_slot, rng)
    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="reschedule",
            language="es", from_number=patient["phone_display"],
            started_at=iso(started), duration_ms=duration_ms, outcome="reschedule",
        ),
        appointment_row=dict(
            id=appt_id, status=status, patient_id=patient_id,
            patient_name=full_name(patient), patient_phone=patient["phone_display"],
            patient_email=None, provider_id=provider.provider_id, provider_name=provider.name,
            specialty_id=provider.specialty_id, specialty_name=provider.specialty_name,
            site_id=provider.site_id, site_name=provider.site_name,
            slot_start=iso(new_slot), slot_end=iso(slot_end), insurer=patient["insurer"],
            appointment_type_id=appt_type_id, appointment_type_name=appt_type_name,
            reason="Reprogramada a petición del paciente.",
        ),
    )


def make_cancel_call(rng: random.Random, call_date: date) -> SeedCall:
    patient_id = rng.choice(ADULT_PATIENT_IDS)
    patient = PATIENT_BY_ID[patient_id]
    candidates = [p for p in BOOKABLE_PROVIDERS if p.provider_id not in patient["refused"]]
    provider = rng.choice(candidates)
    started = random_call_time(call_date, rng)
    call_id = f"SEED-cancel-{uuid4().hex[:12]}"
    new_patient = not patient["has_visited_before"]
    appt_type_id, appt_type_name = appointment_type_for(provider, new_patient)
    slot = random_slot(call_date, provider, rng, span_days=10)
    slot_end = slot + timedelta(minutes=15 if appt_type_id.endswith("review") else 30)
    appt_id = f"A{uuid4().hex[:8].upper()}"

    events = base_events(call_id, started, patient["phone_display"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Buenas, soy {full_name(patient)}. Tengo que anular la cita con {provider.name}, "
        "al final no voy a poder ir."))
    t += timedelta(seconds=4)
    events.extend(tool_pair(call_id, t, "list_appointments", {"patient_id": patient_id},
        {
            "patient": patient_ref(patient_id, patient),
            "appointments": [{"appointment_id": appt_id, "start_time": iso(slot)}],
        }))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "assistant", "Entendido, se la cancelo ahora mismo."))
    t += timedelta(seconds=2)
    payload = {"call_id": call_id, "appointment_id": appt_id}
    events.extend(submit_events(call_id, t, "cancel", payload))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant", "Cita cancelada. Que tenga buen día."))
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=3, tools=1,
        actions=[{"route": "cancel", "payload": payload}], duration_ms=duration_ms))

    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="cancellation",
            language="es", from_number=patient["phone_display"],
            started_at=iso(started), duration_ms=duration_ms, outcome="cancel",
        ),
        appointment_row=dict(
            id=appt_id, status="cancelled", patient_id=patient_id,
            patient_name=full_name(patient), patient_phone=patient["phone_display"],
            patient_email=None, provider_id=provider.provider_id, provider_name=provider.name,
            specialty_id=provider.specialty_id, specialty_name=provider.specialty_name,
            site_id=provider.site_id, site_name=provider.site_name,
            slot_start=iso(slot), slot_end=iso(slot_end), insurer=patient["insurer"],
            appointment_type_id=appt_type_id, appointment_type_name=appt_type_name,
            reason="Cancelada a petición del paciente.",
        ),
    )


def make_register_call(rng: random.Random, call_date: date, caller: dict[str, Any]) -> SeedCall:
    started = random_call_time(call_date, rng)
    call_id = f"SEED-register-{uuid4().hex[:12]}"
    digits = f"{rng.randint(0, 99999999):08d}"
    national_id = digits + dni_letter(digits)
    phone = f"6{rng.randint(10000000, 99999999)}"
    email = (
        f"{caller['given_name'].lower()}.{caller['first_surname'].lower()}"
        "@example.com".replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )

    events = base_events(call_id, started, phone)
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Hola, me llamo {caller['given_name']} {caller['first_surname']} "
        f"{caller['second_surname']}, no he estado nunca en la clínica y quería registrarme."))
    t += timedelta(seconds=4)
    events.extend(tool_pair(call_id, t, "lookup_patient",
        {"query": f"{caller['given_name']} {caller['first_surname']}"}, {"matches": []}))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "assistant",
        "No le encuentro en el sistema, le doy de alta como paciente nuevo. "
        "¿Me confirma su fecha de nacimiento y su DNI?"))
    t += timedelta(seconds=4)
    events.append(
        turn(call_id, t, "user", f"Sí, nací el {caller['dob']}, mi DNI es {national_id}.")
    )
    t += timedelta(seconds=2)
    payload = {
        "call_id": call_id, "given_name": caller["given_name"],
        "first_surname": caller["first_surname"], "second_surname": caller["second_surname"],
        "national_id": national_id, "date_of_birth": caller["dob"], "phone": phone,
        "email": email, "insurer": caller["insurer"],
    }
    events.extend(submit_events(call_id, t, "register", payload))
    t += timedelta(seconds=1)
    events.extend(tool_pair(call_id, t, "confirm_registration", {"national_id": national_id},
        {"patient": patient_ref(caller["patient_id"], caller)}))
    t += timedelta(seconds=1)
    events.append(
        turn(call_id, t, "assistant", "Ya está registrado. Llámenos de nuevo para pedir cita.")
    )
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=3, tools=2,
        actions=[{"route": "register", "payload": payload}], duration_ms=duration_ms))

    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="booking",
            language="es", from_number=phone,
            started_at=iso(started), duration_ms=duration_ms, outcome="register",
        ),
        appointment_row=None,
    )


NO_ACTION_SCENARIOS = ["no_availability", "provider_on_leave", "provider_not_in_network"]


def make_no_action_call(rng: random.Random, call_date: date, reason: str) -> SeedCall:
    patient_id = rng.choice(ADULT_PATIENT_IDS)
    patient = PATIENT_BY_ID[patient_id]
    started = random_call_time(call_date, rng)
    call_id = f"SEED-noaction-{uuid4().hex[:12]}"

    if reason == "provider_on_leave":
        line = (f"Hola, soy {full_name(patient)}, quería cita con {REQUENA.name} "
                "para lo antes posible.")
        reply = (f"Lo siento, {REQUENA.name} está de baja estas semanas y no tiene huecos. "
                 "¿Quiere que le busque otro médico de familia?")
        caller_reply = "No, gracias, ya le vuelvo a llamar más adelante."
    elif reason == "provider_not_in_network":
        line = (f"Hola, soy {full_name(patient)}, necesito cita con Dra. Iglesias, "
                "dermatología, tengo seguro DKV.")
        reply = ("Lo siento, la Dra. Iglesias no admite pacientes de DKV. "
                 "No puedo reservarle esa cita.")
        caller_reply = "Vaya, entiendo. Lo consultaré con mi aseguradora."
    else:
        line = (f"Hola, soy {full_name(patient)}, necesito cita de traumatología "
                "esta misma semana.")
        reply = ("Lo siento, no queda ningún hueco de traumatología en las próximas dos "
                 "semanas.")
        caller_reply = "Vale, probaré a llamar otro día."

    events = base_events(call_id, started, patient["phone_display"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user", line))
    t += timedelta(seconds=2)
    events.extend(tool_pair(call_id, t, "lookup_patient", {"query": full_name(patient)},
        {"patient": patient_ref(patient_id, patient), "matched_fields": ["name"]}))
    t += timedelta(seconds=2)
    events.extend(tool_pair(call_id, t, "check_availability", {"reason": reason},
        {"slots": [], "blocked": [{"restriction": reason}]}))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "assistant", reply))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "user", caller_reply))
    t += timedelta(seconds=2)
    payload = {"call_id": call_id, "reason": reason}
    events.extend(submit_events(call_id, t, "no-action", payload))
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=4, tools=2,
        actions=[{"route": "no-action", "payload": payload}], duration_ms=duration_ms))

    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="info",
            language="es", from_number=patient["phone_display"],
            started_at=iso(started), duration_ms=duration_ms, outcome="no_action",
            detail=reason,
        ),
        appointment_row=None,
    )


def make_escalate_call(rng: random.Random, call_date: date) -> SeedCall:
    patient_id = rng.choice(ADULT_PATIENT_IDS)
    patient = PATIENT_BY_ID[patient_id]
    started = random_call_time(call_date, rng)
    call_id = f"SEED-escalate-{uuid4().hex[:12]}"

    events = base_events(call_id, started, patient["phone_display"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Hola, soy {full_name(patient)}, tengo un dolor muy fuerte en el pecho y "
        "me cuesta respirar."))
    t += timedelta(seconds=1)
    events.extend(tool_pair(call_id, t, "lookup_patient", {"query": full_name(patient)},
        {"patient": patient_ref(patient_id, patient), "matched_fields": ["name"]}))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant",
        "Eso no lo podemos atender por cita. Cuelgue y llame al 112 ahora mismo, o vaya "
        "a urgencias."))
    t += timedelta(seconds=2)
    payload = {"call_id": call_id, "reason": "medical_emergency"}
    events.extend(submit_events(call_id, t, "escalate", payload))
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=2, tools=1,
        actions=[{"route": "escalate", "payload": payload}], duration_ms=duration_ms))

    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="other",
            language="es", from_number=patient["phone_display"],
            started_at=iso(started), duration_ms=duration_ms, outcome="escalate",
            detail="medical_emergency",
        ),
        appointment_row=None,
    )


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def build_plan(count: int, seed: int) -> list[str]:
    """Which scenario each of ``count`` calls should be. At least 65% land on
    ``book`` — a positive outcome that actually secures an appointment — the
    rest split across the other five so the deck still looks like a real
    day's mix of changes, registrations and hard stops."""
    weights = {
        "book": 0.66, "reschedule": 0.10, "cancel": 0.10,
        "register": 0.08, "no_action": 0.04, "escalate": 0.02,
    }
    rng = random.Random(seed)
    plan = []
    for kind, weight in weights.items():
        plan += [kind] * round(count * weight)
    while len(plan) < count:
        plan.append("book")
    plan = plan[:count]
    rng.shuffle(plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=50, help="How many calls to generate.")
    parser.add_argument("--seed", type=int, default=20260920, help="RNG seed, for reproducibility.")
    parser.add_argument(
        "--window-days", type=int, default=15,
        help="How far back from TODAY the call dates may land. Small values "
             "(e.g. 1) concentrate the whole deck on today and yesterday.",
    )
    parser.add_argument(
        "--allow-sundays", action="store_true",
        help="Let a call land on any Sunday in the window, not just TODAY — "
             "off by default (the clinic answers none). TODAY is always "
             "included even when it is one, so the last day never goes empty.",
    )
    parser.add_argument(
        "--recent-focus-pct", type=float, default=0.0,
        help="Fraction of the deck (0-1) reserved for TODAY/TODAY-1 on top "
             "of whatever the random spread already lands there — the rest "
             "still spreads over --window-days so 'activity on the last two "
             "days' does not mean 'nothing but the last two days'.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print a summary; write nothing.")
    args = parser.parse_args()

    if not args.dry_run and not remote.enabled():
        print(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SECRET_KEY) not set; "
            "nothing to write to. Set them in .env or pass --dry-run.",
            file=sys.stderr,
        )
        return 1

    # A "refused" set per patient so a scenario never books that patient with
    # a provider who would refuse their plan (Dra. Iglesias / DKV is the only
    # such pair in the fixtures).
    for p in PATIENTS:
        p["refused"] = {"PR04"} if p["insurer"] == "dkv" else set()
        p["phone_display"] = p["phone"] or f"6{random.randint(10000000, 99999999)}"

    rng = random.Random(args.seed)
    days = clinic_days(
        TODAY - timedelta(days=args.window_days), TODAY, allow_sundays=args.allow_sundays
    )
    if TODAY not in days:  # never skip today just because it is a Sunday
        days.append(TODAY)
    recent_days = [TODAY - timedelta(days=1), TODAY]
    plan = build_plan(args.count, args.seed)

    # Which calls (by index into ``plan``) are pinned to today/yesterday
    # rather than drawn from the whole window — guarantees visible activity
    # there instead of leaving it to chance in a 14-day pool.
    pinned_recent = set()
    if args.recent_focus_pct > 0:
        n_pinned = round(len(plan) * args.recent_focus_pct)
        pinned_recent = set(rng.sample(range(len(plan)), min(n_pinned, len(plan))))

    seed_calls: list[SeedCall] = []
    # Cycles rather than a fixed-size repeat: a --count above len(pool) * 3
    # must not crash on StopIteration, it should just reuse identities/
    # reasons — realistic enough for a demo (the same patient can call more
    # than once) and never wrong for any count this script is asked for.
    register_pool = itertools.cycle(NEW_CALLERS)
    no_action_pool = itertools.cycle(NO_ACTION_SCENARIOS)
    for index, kind in enumerate(plan):
        call_date = rng.choice(recent_days) if index in pinned_recent else rng.choice(days)
        if kind == "book":
            seed_calls.append(make_book_call(rng, call_date))
        elif kind == "reschedule":
            seed_calls.append(make_reschedule_call(rng, call_date))
        elif kind == "cancel":
            seed_calls.append(make_cancel_call(rng, call_date))
        elif kind == "register":
            seed_calls.append(make_register_call(rng, call_date, next(register_pool)))
        elif kind == "no_action":
            seed_calls.append(make_no_action_call(rng, call_date, next(no_action_pool)))
        elif kind == "escalate":
            seed_calls.append(make_escalate_call(rng, call_date))

    seed_calls.sort(key=lambda c: c.calls_row["started_at"])

    print(f"generated {len(seed_calls)} calls "
          f"({sum(1 for c in seed_calls if c.appointment_row)} with an appointment)")
    if args.dry_run:
        for c in seed_calls[:10]:
            print(" ", c.calls_row["started_at"], c.calls_row["outcome"], c.call_id)
        print("  ...")
        return 0

    written_calls = 0
    written_appts = 0
    for sc in seed_calls:
        row = dict(sc.calls_row)
        detail = row.pop("detail", None)
        db.insert_call(**row)
        if detail is not None:
            db.update_call_outcome(sc.call_id, detail=detail)
        if sc.appointment_row is not None:
            call = db.get_call_by_call_id(sc.call_id)
            appt = db.insert_appointment(booking_call_id=call.id, **sc.appointment_row)
            db.link_call_to_appointment(call.id, appt.id)
            written_appts += 1
        written_calls += 1
        rows = [
            {
                "event_hash": remote_event_hash(e),
                "ts": iso(e["ts"]) if isinstance(e["ts"], datetime) else str(e["ts"]),
                "call_id": e["call_id"],
                "kind": e["kind"],
                "event": json_safe(e),
            }
            for e in sc.events
        ]
        remote.upsert("call_events", rows, "event_hash")

    print(f"wrote {written_calls} calls, {written_appts} appointments, "
          f"{sum(len(c.events) for c in seed_calls)} call_events")
    return 0


def json_safe(event: dict[str, Any]) -> dict[str, Any]:
    import json

    def default(value: Any) -> Any:
        # A bare datetime here is always naive Europe/Madrid wall-clock (every
        # event builder above works in that clock); without the explicit
        # offset Postgres stores it as UTC and every event on a call reads
        # two hours later than its own ``calls.started_at``.
        if isinstance(value, datetime):
            return iso(value)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return json.loads(json.dumps(event, default=default, ensure_ascii=False))


def remote_event_hash(event: dict[str, Any]) -> str:
    import hashlib
    import json

    safe = json_safe(event)
    return hashlib.sha256(
        json.dumps(safe, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
