"""``/api/wall`` clinic settings, pathways and patterns.

Three editable documents, all in Postgres:

* ``clinic_settings`` — one row, the booking lead time and how many
  identification fields a caller must confirm. ``vortex/clinic_policy.py``
  reads the same row, so a PUT here changes what the line does on the next
  call.
* ``wall_documents`` — one jsonb row per ``kind``. ``pathways`` and
  ``patterns`` are the two the editors save. The rows are seeded once by
  ``database/seed/wall_documents.sql``; the defaults below are only what a
  project that has never been seeded serves, so the editors open on an empty
  canvas instead of a 500.

The SPA no longer ships these as JSON files: an editor that saves to the
server must also load from it, or a reload silently reverts the save.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("vortex.api")
router = APIRouter()

STORE_DOWN = {"error": "store_unavailable"}

#: What an unseeded project serves. Minimal on purpose: an empty canvas the
#: editor can build on, never a second copy of the seed data (that lives in
#: ``database/seed/wall_documents.sql`` and nowhere else).
DEFAULT_DOCUMENTS: dict[str, dict[str, Any]] = {
    "pathways": {"pathways": []},
    "patterns": {
        "patterns": [],
        "specialtyRecallDays": {"default": 365},
        "dataSources": {},
    },
}


def _document(kind: str) -> dict[str, Any]:
    from database import db

    try:
        body = db.get_wall_document(kind)
    except Exception:
        log.warning("wall_documents read failed for %s; serving the empty default", kind)
        body = None
    if body is None:
        return dict(DEFAULT_DOCUMENTS.get(kind, {}))
    return body


def _clinic_settings_json(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "minimumBookingLeadHours": int(values["minimum_booking_lead_hours"]),
        "patientIdentificationFieldsRequired": int(
            values["patient_identification_fields_required"]
        ),
        "callTimeCapMinutes": int(values["call_time_cap_minutes"]),
    }


@router.get("/clinic-settings")
def wall_clinic_settings_get() -> JSONResponse:
    from database import db

    return JSONResponse(_clinic_settings_json(db.get_clinic_settings()))


@router.put("/clinic-settings")
async def wall_clinic_settings_put(request: Request) -> JSONResponse:
    from database import db
    from vortex.clinic_policy import reset_cache

    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse({"error": "object required"}, status_code=422)
    try:
        lead = payload.get("minimumBookingLeadHours", payload.get("minimum_booking_lead_hours", 24))
        fields = payload.get(
            "patientIdentificationFieldsRequired",
            payload.get("patient_identification_fields_required", 1),
        )
        int(lead)
        int(fields)
    except (TypeError, ValueError):
        return JSONResponse({"error": "numeric settings required"}, status_code=422)
    try:
        saved = db.put_clinic_settings(
            {
                "minimum_booking_lead_hours": lead,
                "patient_identification_fields_required": fields,
            }
        )
    except RuntimeError:
        log.warning("clinic settings not saved: no store configured")
        return JSONResponse(STORE_DOWN, status_code=503)
    reset_cache()
    return JSONResponse(_clinic_settings_json(saved))


@router.get("/pathways")
def wall_pathways_get() -> JSONResponse:
    return JSONResponse(_document("pathways"))


@router.put("/pathways")
async def wall_pathways_put(request: Request) -> JSONResponse:
    from database import db

    payload = await request.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("pathways"), list):
        return JSONResponse({"error": "pathways list required"}, status_code=422)
    try:
        db.put_wall_document("pathways", payload)
    except RuntimeError:
        log.warning("pathways not saved: no store configured")
        return JSONResponse(STORE_DOWN, status_code=503)
    return JSONResponse(payload)


@router.get("/patterns")
def wall_patterns_get() -> JSONResponse:
    return JSONResponse(_document("patterns"))


@router.put("/patterns")
async def wall_patterns_put(request: Request) -> JSONResponse:
    from database import db

    payload = await request.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("patterns"), list):
        return JSONResponse({"error": "patterns list required"}, status_code=422)
    try:
        db.put_wall_document("patterns", payload)
    except RuntimeError:
        log.warning("patterns not saved: no store configured")
        return JSONResponse(STORE_DOWN, status_code=503)
    return JSONResponse(payload)
