"""Wall APIs for call settings, pathways, patterns, and the patient timeline."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from nicegui.testing import User

from database import db
from vortex.observability.calllog import CallLog

MADRID = ZoneInfo("Europe/Madrid")


async def test_clinic_settings_get_defaults_and_put(offline_settings, user: User) -> None:
    response = await user.http_client.get("/api/wall/clinic-settings")
    assert response.status_code == 200
    body = response.json()
    assert body["minimumBookingLeadHours"] == 24
    assert body["patientIdentificationFieldsRequired"] == 1

    saved = await user.http_client.put(
        "/api/wall/clinic-settings",
        json={"minimumBookingLeadHours": 48, "patientIdentificationFieldsRequired": 2},
    )
    assert saved.status_code == 200
    assert saved.json()["minimumBookingLeadHours"] == 48
    again = await user.http_client.get("/api/wall/clinic-settings")
    assert again.json()["patientIdentificationFieldsRequired"] == 2


async def test_pathways_seed_then_put(offline_settings, user: User) -> None:
    response = await user.http_client.get("/api/wall/pathways")
    assert response.status_code == 200
    assert response.json()["pathways"]
    payload = {
        "pathways": [{"id": "custom", "name": "Custom", "nodes": []}],
        "selectedId": "custom",
    }
    put = await user.http_client.put("/api/wall/pathways", json=payload)
    assert put.status_code == 200
    again = await user.http_client.get("/api/wall/pathways")
    assert again.json()["selectedId"] == "custom"


async def test_patterns_seed_then_put(offline_settings, user: User) -> None:
    response = await user.http_client.get("/api/wall/patterns")
    assert response.status_code == 200
    assert response.json()["patterns"]
    payload = {**response.json(), "selectedId": response.json()["patterns"][0]["id"]}
    put = await user.http_client.put("/api/wall/patterns", json=payload)
    assert put.status_code == 200


async def test_patient_timeline_merges_visits_and_calls(offline_settings, user: User) -> None:
    log = CallLog("CA-tl", offline_settings.calls_log_path)
    log.event("call.started", from_number="+34612345678", voice="stub", clinic="fake")
    log.tool_called("find_patient", {"name": "Marta"})
    log.tool_returned(
        "find_patient",
        {"status": "found", "patient": {"patient_id": "P00042", "full_name": "Marta Ruiz López"}},
        20,
    )
    log.event("call.ended", reason="hangup")
    log.summary(reason="hangup")

    with db.connection(offline_settings.product_db_path) as conn:
        call = db.insert_call(
            conn,
            call_id="CA-book",
            direction="inbound",
            purpose="booking",
            started_at="2026-09-10T10:00:00+02:00",
            outcome="book",
        )
        db.insert_appointment(
            conn,
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
