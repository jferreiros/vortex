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

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from vortex.line.confirmation_calls import CALL_JOBS, ConfirmationCall
from vortex.line import sms as line_sms
from vortex.line.pathways import (
    PATHWAYS,
    Pathway,
    PathwayEvent,
    fire_pathway,
    pathway_for,
    register_pathway,
)
from vortex.settings import get_settings

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




# --- runtime pathway execution ---------------------------------------------

#: The admin ``wall_documents`` row and the live ``PATHWAYS`` registry are
#: deliberately separate: one is clinic-editable configuration, the other is
#: executable code. The two built-ins below already exist in code, so their
#: admin ids are exact registry names. A document id that does not name a
#: registry entry is auto-registered as an editor-defined follow-up pathway
#: and served back as ``untested`` rather than silently dead.
_BUILTIN_ADMIN_IDS = {
    "cancel-rebooking-call": "appointment_cancelled",
    "booked-confirmation-call": "appointment_booked",
}


def _slugify_pathway_name(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "wall_configured_pathway"


def _registry_name_for_document(document: dict[str, Any], kind: str) -> str:
    """The live registry entry an admin pathway maps to.

    Built-ins keep their exact runtime name; editor-created pathways become
    ``wall_<kind>_<slug>`` so a rename cannot collide with the code paths.
    """
    pathway_id = str(document.get("id") or "").strip()
    if pathway_id in _BUILTIN_ADMIN_IDS:
        return _BUILTIN_ADMIN_IDS[pathway_id]
    base = str(document.get("name") or pathway_id or "wall pathway")
    return f"wall_{_slugify_pathway_name(base)}"


def _editor_call_shape(document: dict[str, Any]) -> dict[str, Any]:
    for node in document.get("nodes") or []:
        shape = node.get("shape") or {}
        if shape.get("family") == "call":
            return shape
    return {}


def ensure_wall_pathways_registered(documents: list[dict[str, Any]], kind: str) -> None:
    """Auto-register editor pathways so every UI row can be exercised.

    Runtime jobs own the script; editor-defined rows get the existing
    confirmation job so a test queue proves the pathway wiring without
    inventing a competing call stack.
    """
    for document in documents:
        name = _registry_name_for_document(document, kind)
        if name not in PATHWAYS:
            register_pathway(
                Pathway(
                    name=name,
                    job="appointment_confirmation",
                    motivo="call_now",
                    summary=(
                        "Editor-defined follow-up pathway from the wall document "
                        f"{document.get('id') or document.get('name') or name!r}."
                    ),
                )
            )


def _runtime_pathway_rows(documents: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for document in documents:
        registry_name = _registry_name_for_document(document, kind)
        runtime = pathway_for(registry_name)
        shape = _editor_call_shape(document)
        rows.append(
            {
                "id": document.get("id") or registry_name,
                "name": document.get("name") or document.get("id") or registry_name,
                "registry_name": registry_name,
                "job": runtime.job,
                "motivo": runtime.motivo,
                "summary": runtime.summary,
                "enabled": bool(document.get("enabled", True)),
                "job_registered": runtime.job in CALL_JOBS,
                "trigger": (document.get("nodes") or [{}])[0].get("description", ""),
                "call_shape": shape.get("type") or "",
                "when": (document.get("nodes") or [{}])[-1].get("when"),
            }
        )
    return rows




async def fire_document_step(
    pathway_name: str,
    node: dict[str, Any],
    *,
    settings,
    now,
    patient_id: str,
    appointment_id: str,
    to: str,
) -> dict[str, Any]:
    """Execute one editor node as proof that its UI shape has a backend.

    Call nodes queue through the shared pathway worker; message nodes send an
    SMS only to the explicitly supplied demo recipient and otherwise report a
    dry run. Visit nodes are informational steps, not backend actions.
    """
    shape = node.get("shape") or {}
    family = shape.get("family")
    step_type = shape.get("type") or family or "step"
    if family == "call":
        call = await fire_pathway(
            settings,
            pathway_name,
            PathwayEvent(
                to=to,
                appointment_at=now + timedelta(hours=24),
                language="es",
                patient_id=patient_id,
                appointment_id=appointment_id,
            ),
            now=now,
        )
        return {
            "kind": "call",
            "type": step_type,
            "status": "queued" if call is not None else "skipped",
            "detail": "outbound call queued through the pathway worker"
            if call is not None
            else "guarded: no target or outbound calls disabled",
            "call": asdict(call) if call is not None else None,
        }
    if family == "message":
        if not to:
            return {
                "kind": "message",
                "type": step_type,
                "status": "skipped",
                "detail": "no demo recipient supplied",
            }
        client = line_sms.make_sms_client(settings)
        try:
            result = await client.send(
                to=to,
                body=f"Vortex demo: paso '{node.get('description') or step_type}' del pathway.",
            )
        finally:
            await client.aclose()
        return {
            "kind": "message",
            "type": step_type,
            "status": result.status,
            "detail": result.detail,
            "to": result.to,
            "sid": result.sid,
        }
    return {
        "kind": family or "step",
        "type": step_type,
        "status": "not_applicable",
        "detail": "a visit step is a clinical event, not an outbound action",
    }

def _call_to_dict(call: ConfirmationCall) -> dict[str, Any]:
    return asdict(call)


@router.get("/pathways/runtime")
def wall_pathways_runtime() -> JSONResponse:
    """The pathways rows the UI renders, joined with live runtime wiring."""
    settings = get_settings()
    documents = _document("pathways").get("pathways")
    documents = documents if isinstance(documents, list) else []
    ensure_wall_pathways_registered(documents, "pathways")
    return JSONResponse(
        {
            "ok": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "subsystem_enabled": bool(settings.confirmation_calls),
            "twilio_ready": bool(
                settings.twilio_account_sid
                and settings.twilio_auth_token
                and settings.twilio_from_number
                and settings.public_base_url
            ),
            "pathways": _runtime_pathway_rows(documents, "pathways"),
        }
    )


@router.post("/pathways/{pathway_id}/test-fire")
async def wall_pathway_test_fire(pathway_id: str, request: Request) -> JSONResponse:
    """Queue the pathway for a synthetic future appointment.

    This proves the UI row really reaches ``fire_pathway`` without touching a
    real appointment and without dialling anybody: the only target accepted
    here is ``VORTEX_CANCEL_CALL_FALLBACK_TO``, and even that stays unused
    when it is empty (the guard returns ``queued: false``).
    """
    settings = get_settings()
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {}
    documents = _document("pathways").get("pathways")
    documents = documents if isinstance(documents, list) else []
    document = next((row for row in documents if row.get("id") == pathway_id), None)
    if document is None:
        return JSONResponse({"error": "unknown_pathway"}, status_code=404)
    if not bool(document.get("enabled", True)):
        return JSONResponse({"error": "pathway_disabled"}, status_code=409)
    ensure_wall_pathways_registered(documents, "pathways")
    registry_name = _registry_name_for_document(document, "pathways")
    lead = timedelta(hours=float(payload.get("hours_ahead", 24)))
    if lead.total_seconds() <= 0:
        return JSONResponse({"error": "hours_ahead must be positive"}, status_code=422)
    now = datetime.now(UTC)
    nodes = document.get("nodes") or []
    node_id = str(payload.get("nodeId") or payload.get("node_id") or "").strip()
    target = str(payload.get("to") or "").strip() or settings.cancel_call_fallback_to
    executable = [
        node
        for node in nodes
        if (node.get("shape") or {}).get("family") in {"call", "message"}
    ]
    if node_id:
        executable = [node for node in executable if str(node.get("id")) == node_id]
        if not executable:
            return JSONResponse({"error": "unknown_or_non_actionable_node"}, status_code=404)
    results = [
        await fire_document_step(
            registry_name,
            node,
            settings=settings,
            now=now,
            patient_id="UI-TEST",
            appointment_id=f"UI-TEST-{pathway_id}",
            to=target,
        )
        for node in executable
    ]
    queued_calls = [row["call"] for row in results if row.get("call")]
    return JSONResponse(
        {
            "ok": True,
            "pathway_id": pathway_id,
            "registry_name": registry_name,
            "steps": results,
            "queued": bool(queued_calls),
            "calls": queued_calls,
            "synthetic": True,
            "dialled": False,
        }
    )


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




def _pattern_suggestion_step(pattern: dict[str, Any]) -> dict[str, Any]:
    suggestion = pattern.get("suggestionNode") or {}
    shape = suggestion.get("shape") or {}
    return {
        "id": f"{pattern.get('id')}-suggestion",
        "shape": shape,
        "description": suggestion.get("description") or pattern.get("name") or "Pattern suggestion",
    }


@router.post("/patterns/{pattern_id}/test-fire")
async def wall_pattern_test_fire(pattern_id: str, request: Request) -> JSONResponse:
    """Run one pattern's suggestion step on a synthetic patient.

    The patient is always ``UI-TEST``: this proves the editor row can reach
    the same outbound machinery without scanning or touching a real patient.
    """
    settings = get_settings()
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {}
    documents = _document("patterns").get("patterns")
    documents = documents if isinstance(documents, list) else []
    pattern = next((row for row in documents if row.get("id") == pattern_id), None)
    if pattern is None:
        return JSONResponse({"error": "unknown_pattern"}, status_code=404)
    if not bool(pattern.get("enabled", True)):
        return JSONResponse({"error": "pattern_disabled"}, status_code=409)
    target = str(payload.get("to") or "").strip() or settings.cancel_call_fallback_to
    now = datetime.now(UTC)
    registry_name = f"pattern_{_slugify_pathway_name(pattern_id)}"
    if registry_name not in PATHWAYS:
        register_pathway(
            Pathway(
                name=registry_name,
                job="appointment_confirmation",
                motivo="call_now",
                summary=f"Editor-defined pattern suggestion from {pattern_id!r}.",
            )
        )
    step = _pattern_suggestion_step(pattern)
    result = await fire_document_step(
        registry_name,
        step,
        settings=settings,
        now=now,
        patient_id="UI-TEST",
        appointment_id=f"UI-TEST-{pattern_id}",
        to=target,
    )
    return JSONResponse(
        {
            "ok": True,
            "pattern_id": pattern_id,
            "step": result,
            "queued": result.get("call") is not None,
            "synthetic": True,
            "dialled": False,
        }
    )


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
