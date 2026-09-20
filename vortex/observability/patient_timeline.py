"""Build a patient timeline the wall can match patterns against.

Visits come from the product diary. Calls that identified the same
``patient_id`` become incoming scheduling events. Confirmation / rebooking
calls that touched one of their appointments become outgoing ones. There is
no SMS/forms store, so those families only appear if a future writer adds
them to ``appointments.reason``-style metadata — the matcher already
tolerates a visits-only history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from vortex.contract import MADRID
from vortex.observability.view import CallCard


def _day(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(iso)
    except ValueError:
        return iso[:10]
    if stamp.tzinfo is None:
        local = stamp.replace(tzinfo=MADRID)
    else:
        local = stamp.astimezone(MADRID)
    return local.date().isoformat()


def _specialty(name: str | None) -> str | None:
    if not name:
        return None
    return name.strip().lower() or None


def events_from_appointments(rows: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        day = _day(row.slot_start)
        if not day:
            continue
        kind = row.appointment_type_name or "consulta"
        events.append(
            {
                "id": f"visit:{row.id}",
                "shape": {"family": "visit", "type": "standard consultation"},
                "description": kind,
                "date": day,
                "specialty": _specialty(row.specialty_name) or _specialty(row.specialty_id),
                "chainLabel": kind,
                "status": row.status,
            }
        )
    return events


def events_from_calls(
    cards: list[CallCard], *, patient_id: str, visits: list[Any] | None = None
) -> list[dict[str, Any]]:
    """``visits`` (the same rows ``events_from_appointments`` draws on) lets a
    cancel/reschedule call learn the specialty of the appointment its own
    payload only names by id — every per-specialty pattern (``cancelled-
    without-replacement`` included) filters a call out entirely when it
    carries no specialty at all, so without this a cancellation could never
    match one."""
    specialty_by_appt_id = {
        v.id: (_specialty(v.specialty_name) or _specialty(v.specialty_id))
        for v in (visits or [])
    }
    events: list[dict[str, Any]] = []
    for card in cards:
        if card.patient_id != patient_id:
            continue
        day = _day(card.started_at)
        if not day:
            continue
        if card.action_kind == "book":
            desc, chain, kind = "Cita concertada", "Booked call", "scheduling"
        elif card.action_kind == "reschedule":
            desc, chain, kind = "Cita cambiada", "Reschedule", "scheduling"
        elif card.action_kind == "cancel":
            # Its own type, not the generic "scheduling": matchPattern.js's
            # isCancellation() (cancelled-without-replacement) reads exactly
            # this field, not the "action" one the isBook() checks use.
            desc, chain, kind = "Cita anulada", "Cancel", "cancellation"
        elif card.status == "live":
            desc, chain, kind = "Llamada en curso", "Live call", "scheduling"
        else:
            desc, chain, kind = "Llamada", "Call", "scheduling"
        appointment_id = None
        if isinstance(card.action_payload, dict):
            appointment_id = card.action_payload.get("appointment_id")
        events.append(
            {
                "id": f"call:{card.call_id}",
                "shape": {
                    "family": "call",
                    "subfamily": "incoming",
                    "type": kind,
                },
                "description": desc,
                "date": day,
                "specialty": specialty_by_appt_id.get(appointment_id),
                "chainLabel": chain,
                "action": card.action_kind,
            }
        )
    return events


def merge_events(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [e for group in groups for e in group]
    merged.sort(key=lambda e: (e.get("date") or "", e.get("id") or ""))
    return merged
