"""``/api/wall/patient-timeline/{patient_id}`` — one patient's history.

Merges two sources: the ``appointments`` rows in Postgres (what was booked)
and the calls in the event feed that named this patient (what was said). The
reject route remembers a suggestion the clinic dismissed, so the same pattern
match does not come back on the next load.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from vortex.api import _shared
from vortex.observability import callfeed
from vortex.observability.patient_timeline import (
    events_from_appointments,
    events_from_calls,
    merge_events,
)
from vortex.observability.view import build_calls

log = logging.getLogger("vortex.api")
router = APIRouter()

#: How far back a patient's history reads. A recall pattern spans a year, so
#: the window has to be wider than one.
TIMELINE_DAYS = 400


@router.get("/patient-timeline/{patient_id}")
def wall_patient_timeline(patient_id: str) -> JSONResponse:
    from database import db

    visits = db.list_appointments(patient_id=patient_id, statuses=())
    rejected = db.list_suggestion_rejections(patient_id)
    cutoff = datetime.now(UTC) - timedelta(days=TIMELINE_DAYS)
    events, _health, _source = _shared.load_events(
        f"timeline:{patient_id}", since=cutoff, cache_ttl=callfeed.INSIGHTS_CACHE_TTL_S
    )
    cards = build_calls(events)
    events = merge_events(
        events_from_appointments(visits),
        events_from_calls(cards, patient_id=patient_id, visits=visits),
    )
    name = next((v.patient_name for v in visits if v.patient_name), None)
    if not name:
        name = next(
            (c.patient_name for c in cards if c.patient_id == patient_id and c.patient_name), None
        )
    return JSONResponse(
        {
            "patientId": patient_id,
            "name": name or patient_id,
            "events": events,
            "rejectedPatternIds": rejected,
        }
    )


@router.post("/patient-timeline/{patient_id}/reject")
async def wall_patient_timeline_reject(patient_id: str, request: Request) -> JSONResponse:
    from database import db

    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "object required"}, status_code=422)
    pattern_id = str(payload.get("patternId") or payload.get("pattern_id") or "").strip()
    if not pattern_id:
        return JSONResponse({"error": "patternId required"}, status_code=422)
    try:
        db.add_suggestion_rejection(patient_id, pattern_id)
    except RuntimeError:
        log.warning("suggestion rejection not saved: no store configured")
        return JSONResponse({"error": "store_unavailable"}, status_code=503)
    rejected = db.list_suggestion_rejections(patient_id)
    return JSONResponse({"patientId": patient_id, "rejectedPatternIds": rejected})
