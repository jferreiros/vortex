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


def events_from_calls(cards: list[CallCard], *, patient_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for card in cards:
        if card.patient_id != patient_id:
            continue
        day = _day(card.started_at)
        if not day:
            continue
        if card.action_kind == "book":
            desc, chain = "Cita concertada", "Booked call"
        elif card.action_kind == "reschedule":
            desc, chain = "Cita cambiada", "Reschedule"
        elif card.action_kind == "cancel":
            desc, chain = "Cita anulada", "Cancel"
        elif card.status == "live":
            desc, chain = "Llamada en curso", "Live call"
        else:
            desc, chain = "Llamada", "Call"
        events.append(
            {
                "id": f"call:{card.call_id}",
                "shape": {
                    "family": "call",
                    "subfamily": "incoming",
                    "type": "scheduling",
                },
                "description": desc,
                "date": day,
                "specialty": None,
                "chainLabel": chain,
                "action": card.action_kind,
            }
        )
    return events


def merge_events(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [e for group in groups for e in group]
    merged.sort(key=lambda e: (e.get("date") or "", e.get("id") or ""))
    return merged
