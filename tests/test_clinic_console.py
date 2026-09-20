"""Wall APIs for call settings, pathways, patterns, and the patient timeline.

Every route here reads or writes Postgres (``clinic_settings``,
``wall_documents``, ``appointments``, ``suggestion_rejections``), so the whole
module needs a migrated Supabase project. The one exception is the
unconfigured-store test at the bottom: it asserts what a *missing* project
looks like on the wire, which is the state the tests above skip on.
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from nicegui.testing import User

from database import db
from vortex.observability.calllog import CallLog

MADRID = ZoneInfo("Europe/Madrid")

HAS_DB = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
needs_db = pytest.mark.skipif(not HAS_DB, reason="needs migrated Supabase")


@needs_db
async def test_clinic_settings_get_defaults_and_put(user: User) -> None:
    response = await user.http_client.get("/api/wall/clinic-settings")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["minimumBookingLeadHours"], int)
    assert isinstance(body["patientIdentificationFieldsRequired"], int)

    saved = await user.http_client.put(
        "/api/wall/clinic-settings",
        json={"minimumBookingLeadHours": 48, "patientIdentificationFieldsRequired": 2},
    )
    assert saved.status_code == 200
    assert saved.json()["minimumBookingLeadHours"] == 48
    again = await user.http_client.get("/api/wall/clinic-settings")
    assert again.json()["patientIdentificationFieldsRequired"] == 2


async def test_clinic_settings_refuses_a_non_numeric_body(user: User) -> None:
    """Validation happens before the store, so this holds either way."""
    bad = await user.http_client.put(
        "/api/wall/clinic-settings", json={"minimumBookingLeadHours": "pronto"}
    )
    assert bad.status_code == 422


@needs_db
async def test_pathways_round_trip(user: User) -> None:
    response = await user.http_client.get("/api/wall/pathways")
    assert response.status_code == 200
    assert isinstance(response.json()["pathways"], list)
    payload = {
        "pathways": [{"id": "custom", "name": "Custom", "nodes": []}],
        "selectedId": "custom",
    }
    put = await user.http_client.put("/api/wall/pathways", json=payload)
    assert put.status_code == 200
    again = await user.http_client.get("/api/wall/pathways")
    assert again.json()["selectedId"] == "custom"


@needs_db
async def test_patterns_round_trip(user: User) -> None:
    response = await user.http_client.get("/api/wall/patterns")
    assert response.status_code == 200
    doc = response.json()
    assert isinstance(doc["patterns"], list)
    put = await user.http_client.put("/api/wall/patterns", json={**doc, "selectedId": "x"})
    assert put.status_code == 200


async def test_document_routes_validate_the_body(user: User) -> None:
    for path in ("/api/wall/pathways", "/api/wall/patterns"):
        bad = await user.http_client.put(path, json={"nope": 1})
        assert bad.status_code == 422


@needs_db
async def test_patient_timeline_merges_visits_and_calls(user: User) -> None:
    log = CallLog("CA-tl")
    log.event("call.started", from_number="+34612345678", voice="stub", clinic="fake")
    log.tool_called("find_patient", {"name": "Marta"})
    log.tool_returned(
        "find_patient",
        {"status": "found", "patient": {"patient_id": "P00042", "full_name": "Marta Ruiz López"}},
        20,
    )
    log.event("call.ended", reason="hangup")
    log.summary(reason="hangup")

    call = db.insert_call(
        call_id="CA-book",
        direction="inbound",
        purpose="booking",
        started_at="2026-09-10T10:00:00+02:00",
        outcome="book",
    )
    db.insert_appointment(
        id="A-tl",
        patient_id="P00042",
        patient_name="Marta Ruiz López",
        slot_start=datetime(2026, 9, 25, 10, 0, tzinfo=MADRID).isoformat(),
        slot_end=datetime(2026, 9, 25, 10, 15, tzinfo=MADRID).isoformat(),
        booking_call_id=call.id,
        specialty_name="Cardiology",
        appointment_type_name="consulta",
    )

    response = await user.http_client.get("/api/wall/patient-timeline/P00042")
    assert response.status_code == 200
    body = response.json()
    assert body["patientId"] == "P00042"
    kinds = {e["id"].split(":")[0] for e in body["events"]}
    assert "visit" in kinds
    assert "call" in kinds

    reject = await user.http_client.post(
        "/api/wall/patient-timeline/P00042/reject",
        json={"patternId": "first-visit-then-gap"},
    )
    assert reject.status_code == 200
    assert "first-visit-then-gap" in reject.json()["rejectedPatternIds"]


@pytest.mark.skipif(HAS_DB, reason="describes an unconfigured store")
async def test_documents_serve_an_empty_default_with_no_store(user: User) -> None:
    """No Supabase configured: a read answers the in-code empty document
    rather than a 500, so the editors open on a blank canvas."""
    for path, key in (("/api/wall/pathways", "pathways"), ("/api/wall/patterns", "patterns")):
        response = await user.http_client.get(path)
        assert response.status_code == 200
        assert response.json()[key] == []


@pytest.mark.skipif(HAS_DB, reason="describes an unconfigured store")
async def test_a_write_with_no_store_is_503_not_500(user: User) -> None:
    """The page has to be able to say "not saved". A 500 reads as a bug in
    the editor; a 503 says the store is not there."""
    response = await user.http_client.put("/api/wall/pathways", json={"pathways": []})
    assert response.status_code == 503
    assert response.json()["error"] == "store_unavailable"
