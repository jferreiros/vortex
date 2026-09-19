"""Today's briefing for the Clinic Home page.

A clinic manager's morning page answers four questions from ``calls.jsonl``,
not occupancy (that is the HIS) and not handle time (that is a contact centre):

1. What did the inbound line do to the diary today — booked, moved, cancelled, registered.
2. How much of that stayed off the desk — ended without escalate.
3. Who still needs a person — live calls and escalations, grouped by reason.
4. Where access was lost — unmet demand and cancelled slots not recovered,
   over the last seven days so a quiet morning is not an empty page.

Same ``list[CallCard]`` as ``business_insights``. Spanish labels live here
because this payload is the Clinic View, not the jury wall.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from vortex.observability.business_insights import (
    MADRID,
    cancellation_slots,
    unavailability_reasons,
)
from vortex.observability.view import CallCard

WINDOW_DAYS = 7

DIARY_LABELS: dict[str, str] = {
    "book": "Concertadas",
    "register": "Altas",
    "reschedule": "Cambiadas",
    "cancel": "Canceladas",
    "no-action": "Sin cita",
    "escalate": "A una persona",
    "live": "En curso",
    "ended": "Sin acción enviada",
}

HUMAN_REASON_ES: dict[str, str] = {
    "medical_emergency": "Urgencia médica",
    "patient_not_found": "Paciente no identificado",
    "caller_not_authorised": "Tercero no autorizado",
    "out_of_scope": "Fuera de la línea",
    "en_curso": "En curso",
}


def _started_madrid(card: CallCard) -> datetime | None:
    if not card.started_at:
        return None
    try:
        stamp = datetime.fromisoformat(card.started_at)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(MADRID)


def _mix_key(card: CallCard) -> str:
    if card.live:
        return "live"
    kind = card.action_kind
    if kind in DIARY_LABELS:
        return kind
    return "ended"


def _human_reason(card: CallCard) -> tuple[str, str]:
    if card.live:
        return "en_curso", HUMAN_REASON_ES["en_curso"]
    raw = card.decline_reason or card.reason or "escalate"
    return raw, HUMAN_REASON_ES.get(raw, "Revisar en mostrador")


def _today_snapshot(today: list[CallCard]) -> dict[str, Any]:
    mix_counts: Counter[str] = Counter(_mix_key(c) for c in today)
    mix = [
        {
            "key": key,
            "label": DIARY_LABELS[key],
            "count": mix_counts.get(key, 0),
        }
        for key in (
            "book",
            "register",
            "reschedule",
            "cancel",
            "no-action",
            "escalate",
            "live",
            "ended",
        )
        if mix_counts.get(key, 0)
    ]

    ended = [c for c in today if not c.live]
    escalated = [c for c in today if c.status == "escalated"]
    contained = [c for c in ended if c.status != "escalated"]
    contained_pct = round(100 * len(contained) / len(ended), 1) if ended else None

    needs_human = [c for c in today if c.live or c.status == "escalated"]
    reason_counts: Counter[tuple[str, str]] = Counter(_human_reason(c) for c in needs_human)
    human_reasons = [
        {"key": key, "label": label, "count": count}
        for (key, label), count in reason_counts.most_common()
    ]

    booked = mix_counts.get("book", 0)
    registered = mix_counts.get("register", 0)
    rescheduled = mix_counts.get("reschedule", 0)
    cancelled = mix_counts.get("cancel", 0)

    return {
        "calls": len(today),
        "ended": len(ended),
        "booked": booked,
        "registered": registered,
        "rescheduled": rescheduled,
        "cancelled": cancelled,
        "diary_touched": booked + rescheduled + cancelled,
        "contained_pct": contained_pct,
        "escalated": len(escalated),
        "live": mix_counts.get("live", 0),
        "needs_human": len(needs_human),
        "human_reasons": human_reasons,
        "mix": mix,
    }


def home_overview(cards: list[CallCard], *, now: datetime | None = None) -> dict[str, Any]:
    """Payload for GET /api/wall/home-overview."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local_now = now.astimezone(MADRID)
    today_date = local_now.date()
    week_cut = local_now - timedelta(days=WINDOW_DAYS)

    today: list[CallCard] = []
    week: list[CallCard] = []
    for card in cards:
        started = _started_madrid(card)
        if started is None:
            continue
        if started.date() == today_date:
            today.append(card)
        if started >= week_cut:
            week.append(card)

    return {
        "as_of": local_now.isoformat(),
        "window_days": WINDOW_DAYS,
        "today": _today_snapshot(today),
        "unavailability": unavailability_reasons(week),
        "cancellations": cancellation_slots(week, now=now),
        "calls_in_window": len(week),
    }
