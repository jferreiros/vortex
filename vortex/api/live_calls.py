"""``/api/wall/live-calls`` — the calls in progress right now.

Reads the same "recent" feed every live card on the board does
(``_shared.load_cards`` -> ``callfeed.load_events`` -> ``call_events`` in
Supabase). Ended refused / escalated calls ride along as the two review
tails the page shows under the live list.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from vortex.api import _shared
from vortex.observability import analytics as analytics_pack_module
from vortex.observability import explain
from vortex.observability.business_insights import is_real_call
from vortex.observability.view import CallCard
from vortex.settings import REPO_ROOT

router = APIRouter()

#: Every socket the line handles is inbound (see _live_call_payload's own
#: note) — there is no live queue to read for calls the line is about to
#: place, so this is a wall-cache override only, same pattern as
#: analytics.py's business-insights override. Never committed (see
#: .gitignore's ``wall-cache/*.json``): its absence is the normal state, and
#: the endpoint reports no outbound calls queued.
SCHEDULED_OUTBOUND_CALLS_PATH = REPO_ROOT / "wall-cache" / "scheduled_outbound_calls_override.json"


def _scheduled_outbound_calls_override() -> list[dict[str, Any]]:
    try:
        data = json.loads(SCHEDULED_OUTBOUND_CALLS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return data
    return data.get("calls", []) if isinstance(data, dict) else []

_PHASE_KEY = {
    "listen": "listening",
    "identify": "speaking",
    "decide": "working",
    "submit": "working",
}


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


def _live_call_payload(card: CallCard) -> dict[str, Any]:
    stage_i = max(explain.stage_of(card) - 1, 0)
    stage_id, stage_label, _blurb = explain.STAGES[stage_i]
    tool = _live_tool(card)
    last = card.turns[-1] if card.turns else None
    return {
        "id": card.call_id,
        "patient": card.patient_name or "Sin identificar",
        "patient_id": card.patient_id or "",
        "site": card.provider_name or "",
        "phase": stage_label,
        "phaseKey": _PHASE_KEY.get(stage_id, "listening"),
        "phaseLabel": stage_label,
        "tool": tool,
        "status": card.status,
        "duration": _shared.duration(card),
        "language": _call_language(card),
        # Every socket connection is inbound (the platform only ever
        # dials us — see .claude/skills/call-contract); the only
        # outbound calls this product places are confirmation calls,
        # which do not carry a live turn-by-turn transcript the same
        # way and are not shown on this "in progress right now" list.
        "direction": "inbound",
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
    refused = [c for c in real if c.status == "refused"][:12]
    escalated = [c for c in real if c.status == "escalated"][:12]
    return {
        "calls": [_live_call_payload(c) for c in live],
        "rejected": [_review_payload(c) for c in refused],
        "escalated": [_review_payload(c) for c in escalated],
    }


@router.get("/live-calls")
def wall_live_calls_api() -> JSONResponse:
    """Calls in progress right now, plus today's refused / escalated tails."""
    return JSONResponse(live_calls_payload())


@router.get("/live-calls/stream")
async def wall_live_calls_stream(request: Request, once: bool = False) -> StreamingResponse:
    """Same payload as GET /live-calls, pushed as Server-Sent Events."""
    return _shared.sse_response(request, live_calls_payload, once=once)


@router.get("/scheduled-outbound-calls")
def wall_scheduled_outbound_calls_api() -> JSONResponse:
    """Outbound confirmation / rebooking calls the line has queued to place.

    See ``SCHEDULED_OUTBOUND_CALLS_PATH``: no live source exists for this
    yet, so it is an override-only read.
    """
    return JSONResponse({"calls": _scheduled_outbound_calls_override()})
