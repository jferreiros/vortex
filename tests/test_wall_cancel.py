"""The wall's own cancel routes — the Horarios page's two confirm dialogs.

``/api/wall/agenda/cancel-preview`` counts, ``/api/wall/agenda/cancel`` frees a
doctor's range, ``/api/wall/appointments/cancel`` frees one slot. All three
write ``wall_cancellations`` rows in the product database (tmp_path here) and
the next agenda read drops those slots — a cancel must never need a reload to
show, and a second cancel of the same slot must refuse.
"""

from __future__ import annotations

from pathlib import Path

from nicegui.testing import User

from database import db


async def _doctor_with_bookings(user: User) -> dict:
    """The first catalogue doctor whose diary the pack has filled."""
    options = (await user.http_client.get("/api/wall/agenda-options")).json()
    for doctor in options["doctors"]:
        preview = await user.http_client.post(
            "/api/wall/agenda/cancel-preview",
            json={"provider_id": doctor["id"], "from": "2020-01-01", "to": "2030-12-31"},
        )
        if preview.json().get("count", 0) > 0:
            return doctor
    raise AssertionError("the pack books no doctor — fixture drifted")


async def _first_visit(user: User, doctor_name: str) -> dict:
    """One booked visit row off the doctor's own agenda page — the month
    grid's ``weeks[*][*].visits`` covers more ground than the week's cells."""
    agenda = (
        await user.http_client.get("/api/wall/doctor-agenda", params={"name": doctor_name})
    ).json()
    rows = [
        visit for week in agenda.get("weeks", []) for day in week for visit in day.get("visits", [])
    ]
    rows += [
        cell["visit"]
        for column in agenda.get("days", [])
        for cell in column.get("cells", [])
        if cell.get("visit")
    ]
    for visit in rows:
        if visit.get("provider_id") and visit.get("slot") and visit.get("location_id"):
            return visit
    raise AssertionError("the doctor has no visit rows — fixture drifted")


async def test_range_preview_counts_then_confirm_cancels(user: User, offline_settings) -> None:
    doctor = await _doctor_with_bookings(user)
    body = {"provider_id": doctor["id"], "from": "2020-01-01", "to": "2030-12-31"}

    preview = await user.http_client.post("/api/wall/agenda/cancel-preview", json=body)
    assert preview.status_code == 200
    count = preview.json()["count"]
    assert count > 0

    confirm = await user.http_client.post("/api/wall/agenda/cancel", json=body)
    assert confirm.status_code == 200
    result = confirm.json()
    assert result["ok"] is True
    assert result["doctor"] == doctor["name"]
    assert result["cancelled"] == count
    assert result["appointments_updated"] == 0
    # Every cancelled visit with a patient on it is queued for the callback.
    assert result["rebookings_queued"] > 0

    # The wall_cancellations rows landed in the test's product DB.
    conn = db.connect(Path(offline_settings.product_db_path))
    try:
        rows = db.list_wall_cancellations(conn)
    finally:
        conn.close()
    assert len(rows) == count

    # And the reschedule-callback queue (rebooking.sqlite3 next to the
    # product DB) holds one pending reschedule per queued visit.
    from vortex.diary.rebooking import RebookingStore

    store = RebookingStore(Path(offline_settings.product_db_path).with_name("rebooking.sqlite3"))
    pending = store.pending()
    assert len(pending) == result["rebookings_queued"]
    assert all(
        request.intent == "reschedule"
        and request.status == "pending"
        and request.source_reason == "wall_cancel"
        and request.call_id.startswith("WALLC-")
        for request in pending
    )

    # A second preview sees the slots already gone — nothing left to cancel.
    again = await user.http_client.post("/api/wall/agenda/cancel-preview", json=body)
    assert again.json()["count"] == 0


async def test_single_cancel_frees_the_slot_and_refuses_a_repeat(
    user: User, offline_settings
) -> None:
    doctor = await _doctor_with_bookings(user)
    visit = await _first_visit(user, doctor["name"])
    body = {
        "provider_id": visit["provider_id"],
        "location_id": visit["location_id"],
        "slot_start": visit["slot"],
    }

    resp = await user.http_client.post("/api/wall/appointments/cancel", json=body)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["rebookings_queued"] == 1

    # The slot reads free on the very next agenda read — no reload needed.
    agenda = (
        await user.http_client.get("/api/wall/doctor-agenda", params={"name": doctor["name"]})
    ).json()
    for column in agenda.get("columns", []):
        for cell in column.get("cells", []):
            other = cell.get("visit")
            assert not (
                other
                and other.get("slot") == visit["slot"]
                and other.get("provider_id") == visit["provider_id"]
            )

    # Cancelling the same slot twice is a conflict, never a new row.
    repeat = await user.http_client.post("/api/wall/appointments/cancel", json=body)
    assert repeat.status_code == 409
    assert repeat.json()["error"] == "not_booked"


async def test_cancel_routes_validate_the_body(user: User, offline_settings) -> None:
    bad = await user.http_client.post("/api/wall/agenda/cancel-preview", json={})
    assert bad.status_code == 400
    assert bad.json()["error"] == "missing_doctor"

    no_dates = await user.http_client.post("/api/wall/agenda/cancel", json={"provider_id": "D-1"})
    assert no_dates.status_code == 400
    assert no_dates.json()["error"] == "missing_dates"

    ghost = await user.http_client.post(
        "/api/wall/agenda/cancel-preview",
        json={"provider_id": "NOPE", "from": "2026-01-01", "to": "2026-01-02"},
    )
    assert ghost.status_code == 404
    assert ghost.json()["error"] == "unknown_doctor"

    bad_slot = await user.http_client.post(
        "/api/wall/appointments/cancel",
        json={"provider_id": "D-1", "location_id": "S-1", "slot_start": "not-a-date"},
    )
    assert bad_slot.status_code == 400
    assert bad_slot.json()["error"] == "bad_slot"
