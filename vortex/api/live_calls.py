"""``/api/wall/live-calls`` — the calls in progress right now, then today's.

Reads the same "recent" feed every live card on the board does
(``_shared.load_cards`` -> ``callfeed.load_events`` -> ``call_events`` in
Supabase). ``calls`` lists the in-progress calls first and then every call
that ended today (Europe/Madrid), newest first, so the Home "Live" list and
the Calls page show the day's inbound line rather than an empty panel between
two live calls. Ended refused / escalated calls ride along as the two review
tails the page shows under the live list.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from vortex.api import _shared
from vortex.observability import analytics as analytics_pack_module
from vortex.observability import explain
from vortex.observability.business_insights import is_real_call
from vortex.observability.view import CallCard

log = logging.getLogger("vortex.api")
router = APIRouter()

_PHASE_KEY = {
    "listen": "listening",
    "identify": "speaking",
    "decide": "working",
    "submit": "working",
}

#: Status wording for a finished call, shown where a live call shows its
#: phase. Mirrors ``STATUS_LABEL`` in the wall's ``lib/labels.js``.
_ENDED_PHASE = {
    "booked": "Appointment booked",
    "registered": "Patient registered",
    "rescheduled": "Appointment rescheduled",
    "cancelled": "Appointment cancelled",
    "refused": "No action",
    "escalated": "Escalated",
    "ended": "Ended",
}


#: One ``calls`` read per this many seconds — the SSE stream rebuilds the
#: payload every 0.4 s and a call's direction never changes.
_DIRECTIONS_TTL_S = 10.0
_directions_cache: tuple[float, dict[str, str]] | None = None


def _directions() -> dict[str, str]:
    """``call_id`` -> ``inbound`` / ``outbound`` from ``public.calls``. Empty
    when the store is off; callers default to inbound, which every socket
    connection is."""
    global _directions_cache
    if _directions_cache and time.monotonic() - _directions_cache[0] < _DIRECTIONS_TTL_S:
        return _directions_cache[1]
    try:
        from database import remote

        rows = remote.select("calls", {"select": "call_id,direction"}) or []
    except Exception:
        log.warning("calls direction read failed; every call reads as inbound")
        return {}
    found = {str(r["call_id"]): str(r["direction"]) for r in rows if r.get("call_id")}
    _directions_cache = (time.monotonic(), found)
    return found


def _started_today(card: CallCard, today) -> bool:
    started = _shared.card_started(card)
    return started is not None and started.astimezone(_shared.MADRID).date() == today


def _live_tool(card: CallCard) -> str | None:
    running = next((step for step in reversed(card.tools) if step.status == "running"), None)
    if running is not None:
        return running.name
    return card.tools[-1].name if card.tools else None


def _call_language(card: CallCard) -> str:
    return analytics_pack_module._language(card) or "es"


def _last_spoken(card: CallCard, role: str) -> str:
    for turn in reversed(card.turns):
        if turn.role == role:
            text = (turn.text or "").strip()
            if text:
                return text
    return ""


def _ended_phase(card: CallCard) -> str:
    """What a finished call shows in the phase slot: the booked doctor and
    slot when the call fixed one, otherwise its outcome in words."""
    if card.status in {"booked", "rescheduled"} and card.provider_name and card.slot:
        return f"{card.provider_name} · {card.slot}"
    return _ENDED_PHASE.get(card.status, _ENDED_PHASE["ended"])


def _live_call_payload(card: CallCard, direction: str = "inbound") -> dict[str, Any]:
    if card.live:
        stage_i = max(explain.stage_of(card) - 1, 0)
        stage_id, stage_label, _blurb = explain.STAGES[stage_i]
        phase_key = _PHASE_KEY.get(stage_id, "listening")
    else:
        stage_label = _ended_phase(card)
        phase_key = "done"
    tool = _live_tool(card)
    last = card.turns[-1] if card.turns else None
    return {
        "id": card.call_id,
        "patient": card.patient_name or "Sin identificar",
        "patient_id": card.patient_id or "",
        "site": card.provider_name or "",
        "phase": stage_label,
        "phaseKey": phase_key,
        "phaseLabel": stage_label,
        "tool": tool,
        "status": card.status,
        "duration": _shared.duration(card),
        "time": _shared.clock(card.started_at),
        "reason": card.decline_reason if card.status in {"refused", "escalated"} else None,
        "language": _call_language(card),
        # Every socket connection is inbound (the platform only ever dials
        # us — see .claude/skills/call-contract). The product's own outbound
        # calls (confirmations, rebooking call-backs) are the rows
        # ``public.calls`` marks ``direction='outbound'``.
        "direction": direction,
        "phone": card.from_number or "",
        "lastUser": _last_spoken(card, "user"),
        "lastAgent": _last_spoken(card, "assistant"),
        "lastTurn": (last.text or "").strip() if last else "",
        "lastRole": last.role if last else "",
    }


def _review_payload(card: CallCard) -> dict[str, Any]:
    return {
        "id": card.call_id,
        "patient": card.patient_name or "Sin identificar",
        "patient_id": card.patient_id or "",
        "phone": card.from_number or "",
        "time": _shared.clock(card.last_ts or card.started_at),
        "reason": card.decline_reason or card.reason or card.status,
    }


def live_calls_payload() -> dict[str, Any]:
    cards, _health = _shared.load_cards()
    real = [c for c in cards if is_real_call(c)]
    live = [c for c in real if c.live]
    today = datetime.now(_shared.MADRID).date()
    # ``cards`` is newest first already (``build_calls`` reverses), so the
    # day's finished calls come out most recent at the top.
    ended_today = [c for c in real if not c.live and _started_today(c, today)]
    directions = _directions() if live or ended_today else {}
    refused = [c for c in real if c.status == "refused"][:12]
    escalated = [c for c in real if c.status == "escalated"][:12]
    return {
        "calls": [
            _live_call_payload(c, directions.get(c.call_id, "inbound"))
            for c in [*live, *ended_today]
        ],
        "rejected": [_review_payload(c) for c in refused],
        "escalated": [_review_payload(c) for c in escalated],
    }


@router.get("/live-calls")
def wall_live_calls_api() -> JSONResponse:
    """Calls in progress right now, then today's finished ones, plus the
    refused / escalated review tails."""
    return JSONResponse(live_calls_payload())


@router.get("/live-calls/stream")
async def wall_live_calls_stream(request: Request, once: bool = False) -> StreamingResponse:
    """Same payload as GET /live-calls, pushed as Server-Sent Events."""
    return _shared.sse_response(request, live_calls_payload, once=once)
