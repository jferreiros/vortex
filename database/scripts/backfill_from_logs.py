"""Build the product database's rows out of the call event log.

``database/hooks.py`` writes this database forward-only: one call at a time,
from ``vortex/line/submit.py``, as each submission is accepted. Nothing has
ever written the calls that happened *before* that hook shipped, so a log
full of real calls and an empty ``appointments`` table are the normal state
of a fresh checkout. This script closes that gap, and is the reason the
board's Agenda can show real visits without waiting for new traffic.

Every fact comes from the log; nothing is invented and nothing needs the
clinic API:

- ``call.summary``'s ``actions`` carry the submitted payload *and* the
  platform's verdict, so what lands here is what really happened, the same
  source ``hooks.py`` trusts (the submit's own action, never an intermediate
  tool call a caller later talked the agent out of).
- The payloads name only ids (``PR03``, ``sur``, ``P00980``). The names that
  go with them are recovered from the same call's own ``tool.returned``
  events — ``find_slots`` knows a slot's provider name and duration,
  ``find_patient`` the patient's name and phone, ``list_appointments`` the
  slot a cancel or reschedule targeted, ``clinic_facts`` the site names. A
  name that appears in none of them is left NULL rather than guessed.

Re-running is safe and is the intended way to pick up new calls:
``db.insert_call`` upserts on ``call_id``, appointment ids are derived from
the call rather than randomly minted, and an appointment already present is
updated instead of inserted.

Run it:

    uv run python database/scripts/backfill_from_logs.py
    uv run python database/scripts/backfill_from_logs.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from database import db
from vortex.conversation.language import detect_language
from vortex.observability.calllog import read_calls
from vortex.settings import get_settings

#: Submit verdicts that mean the action really happened. ``dry_run`` counts
#: for the same reason ``database/README.md`` gives: with no PLATFORM_API_KEY
#: nothing is ever "accepted" by a real platform, but the action is as real
#: locally as it would be against one. Only a rejected, late or unknown-call
#: submit means it never happened.
LANDED = frozenset({"accepted", "duplicate", "dry_run"})

#: ``purpose`` and ``outcome`` per submit route. ``purpose`` mirrors the action
#: actually submitted rather than an inferred intent: a ``no-action`` call may
#: have been a question ("info") or a failed identification ("booking"), and
#: the log does not say which, so all three actions that never touch an
#: appointment share the schema's own catch-all.
ACTION_BY_ROUTE: dict[str, tuple[str, str]] = {
    "/api/v1/submit/book": ("booking", "book"),
    "/api/v1/submit/cancel": ("cancellation", "cancel"),
    "/api/v1/submit/reschedule": ("reschedule", "reschedule"),
    "/api/v1/submit/register": ("other", "register"),
    "/api/v1/submit/no-action": ("other", "no_action"),
    "/api/v1/submit/escalate": ("other", "escalate"),
}

#: Which outcome a call is filed under when it landed more than one action —
#: a call that registered a patient *and* booked them is a booking. Highest
#: number wins.
OUTCOME_RANK: dict[str, int] = {
    "no_action": 1,
    "escalate": 2,
    "register": 3,
    "cancel": 4,
    "reschedule": 5,
    "book": 6,
}

#: Fallback appointment length when no ``find_slots`` row or clinic
#: appointment names one — the same default ``database/hooks.py`` uses.
DEFAULT_DURATION_MINUTES = 15

#: Cap on the free-text "motivo" recovered from the caller's own words, as in
#: ``database/hooks.py``'s ``_reason``.
REASON_LIMIT = 240


def is_practice_call(started: dict[str, Any]) -> bool:
    """Whether a ``call.started`` belongs to something other than a real
    caller, by the same markers ``business_insights.is_real_call`` uses."""
    call_id = str(started.get("call_id") or "")
    return (
        call_id.startswith(("probe:", "CA-fake-", "CA-mic-"))
        or started.get("clinic") == "synthetic-data"
        or started.get("voice") == "demo"
    )


class LogFacts:
    """The names and slot detail tool results happen to know.

    Built once per call, with the whole log's index behind it as ``fallback``.
    The call's own view wins: two calls can legitimately see different states
    of the diary, and a row should reflect what *that* call saw. But a
    provider's name, a site's name and a patient's name are facts about the
    clinic rather than about one conversation, so when the call never looked
    them up, borrowing them from a call that did is accurate — and it is the
    only accurate source available, because the offline fixtures in
    ``vortex/clinic/fixtures.py`` disagree with the live roster (they have
    seven providers to the platform's twelve, and give PR03 a different name
    and specialty). A name in neither index is left NULL, never guessed.
    """

    def __init__(self, events: list[dict[str, Any]], fallback: LogFacts | None = None) -> None:
        self.fallback = fallback
        self.patients: dict[str, dict[str, Any]] = {}
        self.providers: dict[str, dict[str, Any]] = {}
        self.specialties: dict[str, str] = {}
        self.sites: dict[str, str] = {}
        self.slots: dict[tuple[str, str], dict[str, Any]] = {}
        self.appointments: dict[str, dict[str, Any]] = {}
        for event in events:
            if event.get("kind") != "tool.returned":
                continue
            result = event.get("result")
            if isinstance(result, dict):
                self._absorb(str(event.get("tool") or ""), result)

    def _note_provider(self, row: dict[str, Any]) -> None:
        """Merge, never replace: ``find_slots`` names a provider but not their
        specialty's name, ``find_provider`` names both. Whichever arrives
        first must not shadow what the other would have added."""
        key = str(row.get("provider_id"))
        known = self.providers.setdefault(key, {})
        for field, value in row.items():
            if value not in (None, "") and not known.get(field):
                known[field] = value
        if row.get("specialty_id") and row.get("specialty_name"):
            self.specialties.setdefault(str(row["specialty_id"]), str(row["specialty_name"]))

    def _absorb(self, tool: str, result: dict[str, Any]) -> None:
        if tool == "find_patient":
            rows = [result.get("patient"), *(result.get("candidates") or [])]
            for row in rows:
                if isinstance(row, dict) and row.get("patient_id"):
                    self.patients.setdefault(str(row["patient_id"]), row)
        elif tool == "find_provider":
            provider = result.get("provider")
            if isinstance(provider, dict) and provider.get("provider_id"):
                self._note_provider(provider)
        elif tool == "find_slots":
            for slot in result.get("slots") or []:
                if not isinstance(slot, dict):
                    continue
                key = (str(slot.get("start")), str(slot.get("provider_id")))
                self.slots.setdefault(key, slot)
                if slot.get("provider_id") and slot.get("provider_name"):
                    self._note_provider(
                        {
                            "provider_id": slot["provider_id"],
                            "name": slot["provider_name"],
                            "specialty_id": slot.get("specialty_id"),
                        }
                    )
        elif tool == "clinic_facts":
            for site in result.get("sites") or []:
                if isinstance(site, dict) and site.get("location_id"):
                    self.sites.setdefault(str(site["location_id"]), str(site.get("name") or ""))
        elif tool == "list_appointments":
            for appointment in result.get("appointments") or []:
                if isinstance(appointment, dict) and appointment.get("appointment_id"):
                    self.appointments.setdefault(str(appointment["appointment_id"]), appointment)

    def slot(self, start: str | None, provider_id: str | None) -> dict[str, Any]:
        key = (str(start), str(provider_id))
        if key in self.slots:
            return self.slots[key]
        return self.fallback.slot(start, provider_id) if self.fallback else {}

    def provider(self, provider_id: str | None) -> dict[str, Any]:
        key = str(provider_id)
        if key in self.providers:
            return self.providers[key]
        return self.fallback.provider(provider_id) if self.fallback else {}

    def provider_name(self, provider_id: str | None) -> str | None:
        row = self.provider(provider_id)
        return row.get("name") or row.get("provider_name")

    def specialty(
        self, provider_id: str | None, slot: dict[str, Any]
    ) -> tuple[str | None, str | None]:
        row = self.provider(provider_id)
        specialty_id = row.get("specialty_id") or slot.get("specialty_id")
        name = row.get("specialty_name")
        if not name and specialty_id:
            name = self.specialty_name(specialty_id)
        return specialty_id, name

    def specialty_name(self, specialty_id: str) -> str | None:
        if specialty_id in self.specialties:
            return self.specialties[specialty_id]
        return self.fallback.specialty_name(specialty_id) if self.fallback else None

    def site_name(self, location_id: str | None) -> str | None:
        key = str(location_id)
        if self.sites.get(key):
            return self.sites[key]
        return self.fallback.site_name(location_id) if self.fallback else None

    def patient(self, patient_id: str | None) -> dict[str, Any]:
        key = str(patient_id)
        if key in self.patients:
            return self.patients[key]
        return self.fallback.patient(patient_id) if self.fallback else {}

    def appointment(self, appointment_id: str) -> dict[str, Any]:
        if appointment_id in self.appointments:
            return self.appointments[appointment_id]
        return self.fallback.appointment(appointment_id) if self.fallback else {}


def full_name(patient: dict[str, Any]) -> str | None:
    parts = [
        str(patient.get(key) or "").strip()
        for key in ("given_name", "first_surname", "second_surname")
    ]
    name = " ".join(part for part in parts if part)
    return name or None


def caller_words(events: list[dict[str, Any]]) -> str:
    """The caller's own turns as one string.

    Consecutive identical texts are collapsed: the line logs a caller turn
    once per transcription frame that finalises it, so the same sentence can
    appear twice in a row and would otherwise be counted twice here.
    """
    said: list[str] = []
    for event in events:
        if event.get("kind") != "turn.user":
            continue
        text = str(event.get("text") or "").strip()
        if text and (not said or said[-1] != text):
            said.append(text)
    return " ".join(said)


def landed_actions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """The distinct actions a call really landed, in the order it sent them.

    A retried identical submit shows up twice (``accepted`` then
    ``duplicate``); the same payload twice is one action, not two.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for action in summary.get("actions") or []:
        if not isinstance(action, dict):
            continue
        if (action.get("result") or {}).get("status") not in LANDED:
            continue
        payload = action.get("payload") or {}
        key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


def appointment_id_for(call_id: str, payload: dict[str, Any]) -> str:
    """A booking's primary key, derived rather than randomly minted.

    ``database/hooks.py`` mints ``LCL-<uuid4>`` because it runs once, live,
    at the moment of the booking. A backfill may run many times over the same
    log, so the id has to be a function of the booking itself — otherwise
    every re-run would insert the same appointment again under a new id.
    """
    seed = f"{call_id}|{payload.get('slot')}|{payload.get('patient_id')}"
    return f"LCL-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def slot_end_for(start: str, minutes: int) -> str:
    return (datetime.fromisoformat(start) + timedelta(minutes=minutes)).isoformat()


def _duration(slot: dict[str, Any], appointment: dict[str, Any]) -> int:
    for source in (slot, appointment):
        value = source.get("duration_minutes")
        if isinstance(value, int) and value > 0:
            return value
    return DEFAULT_DURATION_MINUTES


def write_booking(
    conn: sqlite3.Connection,
    *,
    call_id: str,
    call_pk: int,
    payload: dict[str, Any],
    facts: LogFacts,
    reason: str | None,
) -> str | None:
    slot_start = payload.get("slot")
    patient_id = payload.get("patient_id")
    if not slot_start or not patient_id:
        return None

    appointment_id = appointment_id_for(call_id, payload)
    if db.get_appointment(conn, appointment_id) is not None:
        return appointment_id

    provider_id = payload.get("provider_id")
    slot = facts.slot(slot_start, provider_id)
    patient = facts.patient(patient_id)
    specialty_id, specialty_name = facts.specialty(provider_id, slot)
    db.insert_appointment(
        conn,
        id=appointment_id,
        booking_call_id=call_pk,
        patient_id=str(patient_id),
        patient_name=full_name(patient),
        patient_phone=patient.get("phone") or None,
        patient_email=patient.get("email") or None,
        provider_id=provider_id,
        provider_name=facts.provider_name(provider_id),
        specialty_id=specialty_id,
        specialty_name=specialty_name,
        site_id=payload.get("location_id"),
        site_name=facts.site_name(payload.get("location_id")),
        slot_start=str(slot_start),
        slot_end=slot_end_for(str(slot_start), _duration(slot, {})),
        insurer=payload.get("policy_id"),
        appointment_type_id=payload.get("appointment_type_id"),
        reason=reason,
    )
    return appointment_id


def write_cancellation(
    conn: sqlite3.Connection,
    *,
    call_pk: int,
    payload: dict[str, Any],
    facts: LogFacts,
) -> str | None:
    appointment_id = payload.get("appointment_id")
    if not appointment_id:
        return None
    appointment_id = str(appointment_id)

    if db.get_appointment(conn, appointment_id) is not None:
        db.update_appointment(conn, appointment_id, status="cancelled")
        return appointment_id

    known = facts.appointment(appointment_id)
    if not known or not known.get("start"):
        # The clinic is read-only and this call never listed the appointment
        # it cancelled, so its slot and patient are genuinely unrecoverable
        # here. The call still gets its row; only the link is missing.
        return None

    provider_id = known.get("provider_id")
    specialty_id, specialty_name = facts.specialty(provider_id, {})
    patient = facts.patient(known.get("patient_id"))
    start = str(known["start"])
    db.insert_appointment(
        conn,
        id=appointment_id,
        booking_call_id=call_pk,
        status="cancelled",
        patient_id=str(known.get("patient_id") or ""),
        patient_name=full_name(patient),
        patient_phone=patient.get("phone") or None,
        patient_email=patient.get("email") or None,
        provider_id=provider_id,
        provider_name=known.get("provider_name") or facts.provider_name(provider_id),
        specialty_id=specialty_id,
        specialty_name=specialty_name,
        site_id=known.get("location_id"),
        site_name=facts.site_name(known.get("location_id")),
        slot_start=start,
        slot_end=slot_end_for(start, _duration({}, known)),
        appointment_type_id=known.get("appointment_type_id"),
    )
    return appointment_id


def write_reschedule(
    conn: sqlite3.Connection,
    *,
    call_pk: int,
    payload: dict[str, Any],
    facts: LogFacts,
) -> str | None:
    appointment_id = payload.get("appointment_id")
    new_start = payload.get("slot")
    if not appointment_id or not new_start:
        return None
    appointment_id = str(appointment_id)
    new_start = str(new_start)

    provider_id = payload.get("provider_id")
    known = facts.appointment(appointment_id)
    slot = facts.slot(new_start, provider_id)
    minutes = _duration(slot, known)
    fields: dict[str, Any] = {
        "slot_start": new_start,
        "slot_end": slot_end_for(new_start, minutes),
        "status": "scheduled",
    }
    if provider_id:
        fields["provider_id"] = provider_id
        fields["provider_name"] = facts.provider_name(provider_id)
    if payload.get("location_id"):
        fields["site_id"] = payload["location_id"]
        fields["site_name"] = facts.site_name(payload["location_id"])
    if payload.get("policy_id"):
        fields["insurer"] = payload["policy_id"]

    if db.get_appointment(conn, appointment_id) is not None:
        db.update_appointment(conn, appointment_id, **fields)
        return appointment_id

    if not known.get("patient_id"):
        return None
    specialty_id, specialty_name = facts.specialty(provider_id, slot)
    patient = facts.patient(known.get("patient_id"))
    db.insert_appointment(
        conn,
        id=appointment_id,
        booking_call_id=call_pk,
        patient_id=str(known["patient_id"]),
        patient_name=full_name(patient),
        patient_phone=patient.get("phone") or None,
        patient_email=patient.get("email") or None,
        provider_id=provider_id,
        provider_name=facts.provider_name(provider_id),
        specialty_id=specialty_id,
        specialty_name=specialty_name,
        site_id=payload.get("location_id"),
        site_name=facts.site_name(payload.get("location_id")),
        slot_start=new_start,
        slot_end=slot_end_for(new_start, minutes),
        insurer=payload.get("policy_id"),
        appointment_type_id=known.get("appointment_type_id"),
    )
    return appointment_id


def backfill_call(
    conn: sqlite3.Connection,
    call_id: str,
    events: list[dict[str, Any]],
    stats: Counter[str],
    clinic: LogFacts | None = None,
) -> None:
    started = next((e for e in events if e.get("kind") == "call.started"), None)
    summary = next((e for e in events if e.get("kind") == "call.summary"), None)
    if started is None or summary is None:
        stats["skipped_incomplete"] += 1
        return
    if is_practice_call(started):
        stats["skipped_practice"] += 1
        return

    actions = landed_actions(summary)
    if not actions:
        stats["skipped_no_landed_action"] += 1
        return

    outcomes = [
        ACTION_BY_ROUTE[route]
        for action in actions
        if (route := str(action.get("route") or "")) in ACTION_BY_ROUTE
    ]
    if not outcomes:
        stats["skipped_unknown_route"] += 1
        return
    purpose, outcome = max(outcomes, key=lambda pair: OUTCOME_RANK[pair[1]])

    words = caller_words(events)
    call = db.insert_call(
        conn,
        call_id=call_id,
        direction="inbound",
        purpose=purpose,
        language=detect_language(words) if words else None,
        from_number=started.get("from_number") or None,
        started_at=str(started.get("ts")),
        duration_ms=summary.get("duration_ms"),
        outcome=outcome,
    )
    stats[f"call:{outcome}"] += 1

    facts = LogFacts(events, fallback=clinic)
    appointment_id: str | None = None
    for action in actions:
        route = str(action.get("route") or "")
        payload = action.get("payload") or {}
        if route.endswith("/book"):
            appointment_id = write_booking(
                conn,
                call_id=call_id,
                call_pk=call.id,
                payload=payload,
                facts=facts,
                reason=words[:REASON_LIMIT] or None,
            )
        elif route.endswith("/cancel"):
            appointment_id = write_cancellation(conn, call_pk=call.id, payload=payload, facts=facts)
        elif route.endswith("/reschedule"):
            appointment_id = write_reschedule(conn, call_pk=call.id, payload=payload, facts=facts)
        else:
            continue
        stats["appointment_linked" if appointment_id else "appointment_unrecoverable"] += 1

    if appointment_id:
        db.link_call_to_appointment(conn, call.id, appointment_id)


def backfill(log_path: Path, db_path: Path, *, dry_run: bool = False) -> Counter[str]:
    grouped, meta = read_calls(log_path)
    stats: Counter[str] = Counter()
    stats["log_events"] = meta["events"]
    stats["log_calls"] = meta["calls"]
    if meta.get("truncated"):
        stats["log_truncated"] = 1

    # One index over every call's tool results, standing behind each call's
    # own: the clinic's providers, sites and specialties are the same facts
    # whichever conversation happened to look them up.
    clinic = LogFacts([event for events in grouped.values() for event in events])
    stats["clinic_providers_known"] = len(clinic.providers)
    stats["clinic_sites_known"] = len(clinic.sites)

    with db.connection(db_path) as conn:
        # Chronological, so a later call's reschedule of the same appointment
        # is the one that sticks.
        for call_id in sorted(grouped, key=lambda cid: str(grouped[cid][0].get("ts") or "")):
            backfill_call(conn, call_id, grouped[call_id], stats, clinic=clinic)
        # Counted before any rollback, so a dry run reports the totals it
        # would have committed rather than the empty table it leaves behind.
        stats["rows_calls"] = conn.execute("SELECT count(*) FROM calls").fetchone()[0]
        stats["rows_appointments"] = conn.execute("SELECT count(*) FROM appointments").fetchone()[0]
        if dry_run:
            conn.rollback()
    return stats


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Build the product database from the call log.")
    parser.add_argument("--log", type=Path, default=settings.calls_log_path)
    parser.add_argument("--db", type=Path, default=settings.product_db_path)
    parser.add_argument("--dry-run", action="store_true", help="roll back instead of committing")
    args = parser.parse_args()

    stats = backfill(args.log, args.db, dry_run=args.dry_run)
    print(f"log:  {args.log}")
    print(f"db:   {args.db}{' (dry run, rolled back)' if args.dry_run else ''}")
    for key in sorted(stats):
        print(f"  {key:32s} {stats[key]}")
    # Last, and one line: the board prints only this when it runs the backfill
    # as a start-up subprocess, so it has to be the line worth having.
    print(
        f"backfill: {stats['rows_calls']} calls, {stats['rows_appointments']} appointments"
        f"{' (dry run)' if args.dry_run else ''}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
