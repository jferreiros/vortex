"""Seed specific, named fictitious calls into Supabase.

    uv run python database/scripts/seed_named_calls.py
    uv run python database/scripts/seed_named_calls.py --dry-run

Real names and real-looking phone numbers were given by hand; every other
detail (patient id, national id, date of birth, provider, slot, transcript)
is invented to build a complete, realistic call around them — same shape
``seed_fake_history.py`` writes: one ``public.calls`` row, one
``public.appointments`` row per visit, and a short synthetic transcript in
``public.call_events`` with every tool result carrying the ``patient``/
``slots`` shape the Live feed (``vortex.observability.view.build_call``)
reads a card's name, provider and slot off of.

Cristina Caballero Rivas gets a small history instead of one call: two past,
regular dermatology visits (30 days apart) and no booking since — set up so
``broken-cadence`` in the Patterns document (``database/seed/wall_documents.
sql``, ``asOf: 2026-09-19``) recognizes her as overdue.

Elvira Castro Molina cancels a visit and never rebooks it — ``cancelled-
without-replacement`` in the same document — and then gets an outbound
call today (a ``motivo="call_now"`` rebooking attempt, unanswered) that
lands after everything else this script or seed_fake_history.py writes, so
it is the one on top of the Live feed.

Call ids are prefixed ``SEED-named-`` so they can never collide with a real
Twilio callSid or a scored run, and re-running this is safe: ``calls``/
``appointments`` upsert on their primary key, ``call_events`` dedupes on
``event_hash``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

from seed_fake_history import (  # noqa: E402
    PROVIDER_BY_ID,
    SeedCall,
    appointment_type_for,
    base_events,
    closing_events,
    iso,
    patient_ref,
    slot_ref,
    submit_events,
    tool_pair,
    turn,
)

from database import db, remote  # noqa: E402

#: Two people who each place one ordinary booking call.
PEOPLE: list[dict[str, Any]] = [
    {
        "patient_id": "P00501",
        "given_name": "Marta", "first_surname": "Sierra", "second_surname": "Obea",
        "phone": "+34 605 90 77 84",
        "dob": "1978-06-14",
        "new_patient": True,
        "provider_id": "PR01",  # Dra. Ortiz, general practice, Arenal Centro
        "insurer": "sanitas",
        "call_at": datetime(2026, 9, 18, 10, 15),
        "slot_at": datetime(2026, 9, 24, 9, 30),
        "reason": "Revisión general, primera vez en la clínica.",
    },
    {
        "patient_id": "P00503",
        "given_name": "Francisco", "first_surname": "Jimeno", "second_surname": "Fernández",
        "phone": "+34 662 25 36 01",
        "dob": "1965-11-08",
        "new_patient": True,
        "provider_id": "PR06",  # D. Álvaro Cid, physiotherapy, Arenal Sur
        "insurer": "mapfre",
        "call_at": datetime(2026, 9, 20, 17, 5),
        "slot_at": datetime(2026, 9, 29, 16, 30),
        "reason": "Dolor lumbar, primera visita de fisioterapia.",
    },
]

#: Cristina gets a history, not a single call — see the module docstring.
#: Two dermatology reviews 30 days apart (2026-06-29, 2026-07-29), both
#: already 30+ days overdue by the patterns document's own ``asOf``
#: (2026-09-19), and her one live call asks for the next one without
#: getting it booked — that gap is exactly what ``broken-cadence`` matches.
CRISTINA: dict[str, Any] = {
    "patient_id": "P00502",
    "given_name": "Cristina", "first_surname": "Caballero", "second_surname": "Rivas",
    "phone": "+34 600 00 00 00",
    "dob": "1990-03-22",
    "provider_id": "PR04",  # Dra. Iglesias, dermatology, Arenal Centro
    "insurer": "asisa",
    "visit_dates": [datetime(2026, 6, 29, 11, 15), datetime(2026, 7, 29, 11, 15)],
    "call_at": datetime(2026, 9, 20, 20, 30),
}

#: Elvira cancels and never rebooks — ``cancelled-without-replacement`` in
#: the Patterns document only needs one cancel call with nothing after it,
#: no visit history required. Her outbound call lands *after* Cristina's, so
#: she is the one on top of the Live feed once this script runs, and it is
#: dated today: the pattern's own suggested "Rebook call" placed the same
#: day the gap is noticed, not answered yet.
#:
#: A patient id of her own (not one of PATIENTS' fixture ids): the frontend
#: resolves a patient's "current" specialty off their *last* timeline event
#: of any kind, so if she also turned up in seed_fake_history.py's random
#: 50 (any of them can pick a real fixture id) an unrelated later visit in
#: some other specialty would outrank her cancellation and the match would
#: never fire.
ELVIRA: dict[str, Any] = {
    "patient_id": "P00504",
    "given_name": "Elvira", "first_surname": "Castro", "second_surname": "Molina",
    "phone": "677334455",
    "provider_id": "PR01",  # Dra. Ortiz, general practice, Arenal Centro
    "insurer": "nueva_mutua",
    "original_slot": datetime(2026, 9, 14, 10, 0),
    "cancel_call_at": datetime(2026, 9, 10, 9, 30),
    "outbound_call_at": datetime(2026, 9, 20, 21, 15),
}


def full_name(p: dict[str, Any]) -> str:
    return f"{p['given_name']} {p['first_surname']} {p['second_surname']}"


def make_named_book_call(person: dict[str, Any]) -> SeedCall:
    provider = PROVIDER_BY_ID[person["provider_id"]]
    started = person["call_at"]
    slot = person["slot_at"]
    call_id = f"SEED-named-{uuid4().hex[:12]}"
    appt_type_id, appt_type_name = appointment_type_for(provider, person["new_patient"])
    duration = 15 if appt_type_id.endswith("review") else 30
    slot_end = slot + timedelta(minutes=duration)

    events = base_events(call_id, started, person["phone"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Hola, soy {full_name(person)}, quería pedir cita con {provider.name}."))
    t += timedelta(seconds=4)
    if person["new_patient"]:
        events.append(turn(call_id, t, "assistant",
            "No le encuentro en el sistema, ¿es la primera vez que viene a la clínica?"))
        t += timedelta(seconds=3)
        events.append(turn(call_id, t, "user", "Sí, es la primera vez."))
        t += timedelta(seconds=2)
        events.extend(tool_pair(call_id, t, "lookup_patient", {"query": full_name(person)},
            {"patient": None, "matches": []}))
        t += timedelta(seconds=1)
        events.extend(tool_pair(call_id, t, "register_patient",
            {"given_name": person["given_name"], "first_surname": person["first_surname"],
             "second_surname": person["second_surname"], "date_of_birth": person["dob"],
             "insurer": person["insurer"]},
            {"patient": patient_ref(person["patient_id"], person)}))
    else:
        events.extend(tool_pair(call_id, t, "lookup_patient", {"query": full_name(person)},
            {"patient": patient_ref(person["patient_id"], person), "matched_fields": ["name"]}))
        t += timedelta(seconds=1)
        events.append(
            turn(call_id, t, "assistant", f"Claro, {person['given_name']}, ahora la atiendo.")
        )
    t += timedelta(seconds=3)
    events.extend(tool_pair(call_id, t, "check_availability",
        {"provider_id": provider.provider_id, "appointment_type_id": appt_type_id},
        slot_ref(slot, provider, appt_type_id)))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant",
        f"Tengo un hueco el {slot.strftime('%d/%m')} a las {slot.strftime('%H:%M')} "
        f"en {provider.site_name}, ¿le viene bien?"))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "user", "Perfecto, resérvemelo."))
    t += timedelta(seconds=2)
    payload = {
        "call_id": call_id, "patient_id": person["patient_id"], "provider_id": provider.provider_id,
        "location_id": provider.site_id, "appointment_type_id": appt_type_id,
        "slot": iso(slot), "policy_id": person["insurer"],
    }
    events.extend(submit_events(call_id, t, "book", payload))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant", "Listo, cita confirmada. ¡Hasta pronto!"))
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    tools_used = 3 if person["new_patient"] else 2
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=6, tools=tools_used,
        actions=[{"route": "book", "payload": payload}], duration_ms=duration_ms))

    appt_id = f"LCL-{uuid4().hex[:16]}"
    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="booking",
            language="es", from_number=person["phone"],
            started_at=iso(started), duration_ms=duration_ms, outcome="book",
        ),
        appointment_row=dict(
            id=appt_id, status="scheduled", patient_id=person["patient_id"],
            patient_name=full_name(person), patient_phone=person["phone"], patient_email=None,
            provider_id=provider.provider_id, provider_name=provider.name,
            specialty_id=provider.specialty_id, specialty_name=provider.specialty_name,
            site_id=provider.site_id, site_name=provider.site_name,
            slot_start=iso(slot), slot_end=iso(slot_end), insurer=person["insurer"],
            appointment_type_id=appt_type_id, appointment_type_name=appt_type_name,
            reason=person["reason"],
        ),
    )


def make_cristina_visit_call(visit_slot: datetime) -> SeedCall:
    """One past, already-completed dermatology review — a short, ordinary
    booking call placed a few days ahead of the visit itself."""
    person = CRISTINA
    provider = PROVIDER_BY_ID[person["provider_id"]]
    started = visit_slot - timedelta(days=6, hours=2)
    call_id = f"SEED-named-{uuid4().hex[:12]}"
    appt_type_id, appt_type_name = appointment_type_for(provider, new_patient=False)
    slot_end = visit_slot + timedelta(minutes=15)

    events = base_events(call_id, started, person["phone"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Hola, soy {full_name(person)}, quería mi revisión con {provider.name}."))
    t += timedelta(seconds=3)
    events.extend(tool_pair(call_id, t, "lookup_patient", {"query": full_name(person)},
        {"patient": patient_ref(person["patient_id"], person), "matched_fields": ["name"]}))
    t += timedelta(seconds=2)
    events.extend(tool_pair(call_id, t, "check_availability",
        {"provider_id": provider.provider_id, "appointment_type_id": appt_type_id},
        slot_ref(visit_slot, provider, appt_type_id)))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant",
        f"Tengo el {visit_slot.strftime('%d/%m')} a las {visit_slot.strftime('%H:%M')}, "
        "¿se la confirmo?"))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "user", "Sí, perfecto."))
    t += timedelta(seconds=2)
    payload = {
        "call_id": call_id, "patient_id": person["patient_id"], "provider_id": provider.provider_id,
        "location_id": provider.site_id, "appointment_type_id": appt_type_id,
        "slot": iso(visit_slot), "policy_id": person["insurer"],
    }
    events.extend(submit_events(call_id, t, "book", payload))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant", "Cita confirmada."))
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=4, tools=2,
        actions=[{"route": "book", "payload": payload}], duration_ms=duration_ms))

    appt_id = f"LCL-{uuid4().hex[:16]}"
    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="booking",
            language="es", from_number=person["phone"],
            started_at=iso(started), duration_ms=duration_ms, outcome="book",
        ),
        appointment_row=dict(
            id=appt_id, status="completed", patient_id=person["patient_id"],
            patient_name=full_name(person), patient_phone=person["phone"], patient_email=None,
            provider_id=provider.provider_id, provider_name=provider.name,
            specialty_id=provider.specialty_id, specialty_name=provider.specialty_name,
            site_id=provider.site_id, site_name=provider.site_name,
            slot_start=iso(visit_slot), slot_end=iso(slot_end), insurer=person["insurer"],
            appointment_type_id=appt_type_id, appointment_type_name=appt_type_name,
            reason="Revisión de dermatología, paciente habitual.",
        ),
    )


def make_cristina_current_call() -> SeedCall:
    """Her most recent call: she asks for the follow-up she is overdue for,
    nothing is free soon, and nothing gets booked — the exact gap
    ``broken-cadence`` is meant to catch, left open on purpose."""
    person = CRISTINA
    provider = PROVIDER_BY_ID[person["provider_id"]]
    started = person["call_at"]
    call_id = f"SEED-named-{uuid4().hex[:12]}"

    events = base_events(call_id, started, person["phone"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Hola, soy {full_name(person)}. Hace tiempo que no voy a mi revisión con "
        f"{provider.name} y quería ver si tienen hueco pronto."))
    t += timedelta(seconds=3)
    events.extend(tool_pair(call_id, t, "lookup_patient", {"query": full_name(person)},
        {"patient": patient_ref(person["patient_id"], person), "matched_fields": ["name"]}))
    t += timedelta(seconds=2)
    events.extend(tool_pair(call_id, t, "check_availability",
        {"provider_id": provider.provider_id, "appointment_type_id": "dermatology_review"},
        {"slots": [], "blocked": []}))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "assistant",
        f"Lo siento, {provider.name} no tiene ningún hueco libre en las próximas dos semanas. "
        "¿Quiere que la apunte en lista de espera?"))
    t += timedelta(seconds=3)
    events.append(turn(call_id, t, "user", "Vale, apúnteme y ya me llaman."))
    t += timedelta(seconds=2)
    payload = {"call_id": call_id, "reason": "no_availability"}
    events.extend(submit_events(call_id, t, "no-action", payload))
    t += timedelta(seconds=2)
    events.append(turn(call_id, t, "assistant", "Hecho, la avisamos en cuanto se libere algo."))
    duration_ms = int((t - started).total_seconds() * 1000) + 800
    events.extend(closing_events(call_id, t + timedelta(seconds=1), turns=4, tools=2,
        actions=[{"route": "no-action", "payload": payload}], duration_ms=duration_ms))

    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="inbound", purpose="info",
            language="es", from_number=person["phone"],
            started_at=iso(started), duration_ms=duration_ms, outcome="no_action",
            detail="no_availability",
        ),
        appointment_row=None,
    )


def make_elvira_cancel_call() -> tuple[SeedCall, str]:
    """Inbound: she cancels, and nothing rebooks it — the one condition
    ``cancelled-without-replacement`` checks for. Shaped exactly like
    ``seed_fake_history.make_cancel_call``: the appointment predates this
    system, so its ``booking_call_id`` is this cancelling call itself (see
    ``database/README.md``, "Why booking_call_id is never NULL")."""
    person = ELVIRA
    provider = PROVIDER_BY_ID[person["provider_id"]]
    started = person["cancel_call_at"]
    call_id = f"SEED-named-{uuid4().hex[:12]}"
    appt_type_id, appt_type_name = appointment_type_for(provider, new_patient=False)
    slot = person["original_slot"]
    slot_end = slot + timedelta(minutes=15)
    appt_id = f"A{uuid4().hex[:6]}".upper()

    events = base_events(call_id, started, person["phone"])
    t = started + timedelta(seconds=3)
    events.append(turn(call_id, t, "user",
        f"Buenas, soy {full_name(person)}. Tengo que anular la cita con {provider.name}, "
        "al final no voy a poder ir."))
    t += timedelta(seconds=4)
    events.extend(tool_pair(call_id, t, "list_appointments", {"patient_id": person["patient_id"]},
        {
            "patient": patient_ref(person["patient_id"], person),
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
            language="es", from_number=person["phone"],
            started_at=iso(started), duration_ms=duration_ms, outcome="cancel",
        ),
        appointment_row=dict(
            id=appt_id, status="cancelled", patient_id=person["patient_id"],
            patient_name=full_name(person), patient_phone=person["phone"], patient_email=None,
            provider_id=provider.provider_id, provider_name=provider.name,
            specialty_id=provider.specialty_id, specialty_name=provider.specialty_name,
            site_id=provider.site_id, site_name=provider.site_name,
            slot_start=iso(slot), slot_end=iso(slot_end), insurer=person["insurer"],
            appointment_type_id=appt_type_id, appointment_type_name=appt_type_name,
            reason="Cancelada a petición del paciente.",
        ),
    ), appt_id


def make_elvira_outbound_call(appt_id: str) -> SeedCall:
    """Outbound, placed today: the Patterns document's own suggested action
    for ``cancelled-without-replacement`` ("Offer to rebook the cancelled
    visit") acted on the moment the gap is noticed. Nobody picks up — the
    pattern stays open, which is the point of showing it at all: this is the
    first attempt, not a resolved case. Same shape
    ``confirmation_calls._persist_call_now_row`` writes for a real
    ``motivo="call_now"`` callback, so it reads like a normal one everywhere
    the board shows outbound calls, not like a seeded special case."""
    person = ELVIRA
    started = person["outbound_call_at"]
    call_id = f"WALLC-{uuid4().hex[:12]}"

    events = base_events(call_id, started, person["phone"])
    t = started + timedelta(milliseconds=200)
    # An outbound call already knows who it is dialling — the queue row
    # names the patient before Twilio ever rings — so the card is
    # identified even though nobody answers. Never "Sin identificar" just
    # because the call itself carries no caller turn to parse a name out of.
    events.extend(tool_pair(call_id, t, "load_rebooking_request", {"appointment_id": appt_id},
        {"patient": patient_ref(person["patient_id"], person), "appointment_id": appt_id}))
    t += timedelta(seconds=14)
    duration_ms = int((t - started).total_seconds() * 1000)
    events.append({
        "ts": t, "call_id": call_id, "kind": "call.ended",
        "reason": "no_answer", "media_frames_in": 0, "media_frames_out": 0,
    })
    events.append({
        "ts": t + timedelta(milliseconds=50), "call_id": call_id, "kind": "call.summary",
        "turns": 0, "tools": 1, "actions": [], "duration_ms": duration_ms,
    })

    return SeedCall(
        call_id=call_id,
        events=events,
        calls_row=dict(
            call_id=call_id, direction="outbound", purpose="reschedule",
            language="es", from_number=person["phone"],
            started_at=iso(started), duration_ms=duration_ms, outcome="no_answer",
            appointment_id=appt_id, motivo="call_now",
        ),
        appointment_row=None,
    )


def write(sc: SeedCall) -> None:
    row = dict(sc.calls_row)
    detail = row.pop("detail", None)
    db.insert_call(**row)
    if detail is not None:
        db.update_call_outcome(sc.call_id, detail=detail)
    call = db.get_call_by_call_id(sc.call_id)
    if sc.appointment_row is not None:
        appt = db.insert_appointment(booking_call_id=call.id, **sc.appointment_row)
        db.link_call_to_appointment(call.id, appt.id)
    rows = []
    for e in sc.events:
        ts = iso(e["ts"]) if isinstance(e["ts"], datetime) else str(e["ts"])
        safe = _json_safe(e)
        rows.append({
            "event_hash": _event_hash(safe),
            "ts": ts,
            "call_id": e["call_id"],
            "kind": e["kind"],
            "event": safe,
        })
    remote.upsert("call_events", rows, "event_hash")


def _json_safe(event: dict[str, Any]) -> dict[str, Any]:
    import json

    def default(value: Any) -> Any:
        if isinstance(value, datetime):
            return iso(value)
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    return json.loads(json.dumps(event, default=default, ensure_ascii=False))


def _event_hash(safe_event: dict[str, Any]) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(safe_event, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print a summary; write nothing.")
    args = parser.parse_args()

    if not args.dry_run and not remote.enabled():
        print(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SECRET_KEY) not set.",
            file=sys.stderr,
        )
        return 1

    calls = [make_named_book_call(p) for p in PEOPLE]
    for sc, person in zip(calls, PEOPLE, strict=True):
        row = sc.appointment_row
        print(f"{full_name(person):30s} {person['phone']:20s} "
              f"{row['provider_name']:14s} {row['site_name']:14s} {row['slot_start']}")

    cristina_calls = [make_cristina_visit_call(d) for d in CRISTINA["visit_dates"]]
    cristina_calls.append(make_cristina_current_call())
    print(f"{full_name(CRISTINA):30s} {CRISTINA['phone']:20s} "
          f"{len(CRISTINA['visit_dates'])} past visits, then no_action "
          f"({cristina_calls[-1].calls_row['started_at']})")

    elvira_cancel, elvira_appt_id = make_elvira_cancel_call()
    elvira_outbound = make_elvira_outbound_call(elvira_appt_id)
    elvira_calls = [elvira_cancel, elvira_outbound]
    print(f"{full_name(ELVIRA):30s} {ELVIRA['phone']:20s} "
          f"cancel then outbound no_answer "
          f"({elvira_outbound.calls_row['started_at']}, most recent)")

    all_calls = calls + cristina_calls + elvira_calls
    if args.dry_run:
        return 0

    for sc in all_calls:
        write(sc)
    print(f"wrote {len(all_calls)} calls, "
          f"{sum(1 for c in all_calls if c.appointment_row)} appointments, "
          f"{sum(len(c.events) for c in all_calls)} call_events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
