"""``/api/wall/live-calls`` and ``/api/wall/timeline`` — the SPA's live feed.

A call still in progress (no ``call.ended`` line yet) shows up in ``calls``;
ended no-action / escalate calls land in ``rejected`` / ``escalated``. Both
routes read ``call_events`` in Supabase through
``vortex.observability.callfeed.load_events``, so these need a migrated
project to write into — there is no local log to seed any more.
"""

from __future__ import annotations

import os

import pytest
from nicegui.testing import User

from vortex.observability.calllog import CallLog

needs_db = pytest.mark.skipif(
    not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
    reason="needs migrated Supabase",
)

pytestmark = needs_db


def _live_call(cid: str = "CA-live") -> None:
    log = CallLog(cid)
    log.event("call.started", from_number="+34612345678", voice="stub", clinic="fake")
    log.user_turn("Hola, quería pedir cita para mi hija")
    log.assistant_turn("Claro, ¿me dice el nombre?")
    log.tool_called("find_patient", {"name": "Lucía Ruiz López"})
    log.tool_returned("find_patient", {"status": "found", "patient": {"patient_id": "P00001"}}, 30)
    # No call.ended: the card is still open, i.e. `card.live` is True.


def _ended_call(cid: str = "CA-done") -> None:
    log = CallLog(cid)
    log.event("call.started", from_number="+34600000000", voice="stub", clinic="fake")
    log.user_turn("Quiero cancelar mi cita")
    log.event("call.ended", reason="hangup")
    log.summary(reason="hangup")


def _refused_call(cid: str = "CA-refused") -> None:
    log = CallLog(cid)
    log.event("call.started", from_number="+34611111111", voice="stub", clinic="fake")
    log.user_turn("Quiero una cita mañana")
    log.action_submitted(
        "/api/v1/submit/no-action",
        {"call_id": cid, "reason": "no_availability"},
        {"status": "dry_run"},
    )
    log.event("call.ended", reason="hangup")
    log.summary(reason="hangup")


async def test_live_calls_lists_only_calls_still_in_progress(user: User) -> None:
    _live_call()
    _ended_call()

    response = await user.http_client.get("/api/wall/live-calls")
    assert response.status_code == 200
    calls = response.json()["calls"]

    assert "CA-live" in [c["id"] for c in calls]
    assert "CA-done" not in [c["id"] for c in calls]
    live = next(c for c in calls if c["id"] == "CA-live")
    assert live["status"] == "live"
    assert live["direction"] == "inbound"
    assert live["phone"] == "+34612345678"
    # find_patient is a "decide"-adjacent identify step; the phase reads
    # past "Listen" once the call has looked the patient up.
    assert live["phase"] != ""
    assert live["phaseKey"] in {"listening", "speaking", "working"}
    assert live["lastUser"] == "Hola, quería pedir cita para mi hija"
    assert live["lastAgent"] == "Claro, ¿me dice el nombre?"
    assert live["lastTurn"] == "Claro, ¿me dice el nombre?"
    assert live["lastRole"] == "assistant"
    assert "rejected" in response.json()
    assert "escalated" in response.json()


async def test_live_calls_lists_refused_calls_in_rejected(user: User) -> None:
    _refused_call()
    response = await user.http_client.get("/api/wall/live-calls")
    body = response.json()
    rejected = {c["id"]: c for c in body["rejected"]}
    assert "CA-refused" in rejected
    assert rejected["CA-refused"]["reason"] == "no_availability"


async def test_timeline_includes_stored_turns(user: User) -> None:
    _live_call()
    response = await user.http_client.get("/api/wall/timeline/CA-live")
    assert response.status_code == 200
    items = response.json()["items"]
    turns = [(item["role"], item["text"]) for item in items if item.get("type") == "turn"]
    assert ("user", "Hola, quería pedir cita para mi hija") in turns
    assert ("assistant", "Claro, ¿me dice el nombre?") in turns


async def test_timeline_stream_pushes_a_data_frame(user: User) -> None:
    """``once=true`` is the test hook on the SSE routes: one data frame, then
    the stream closes, so the client does not hang on an endless response."""
    _live_call()
    response = await user.http_client.get("/api/wall/timeline/CA-live/stream?once=true")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert '"call_id": "CA-live"' in body
    assert "Hola, quería pedir cita para mi hija" in body


async def test_live_calls_stream_pushes_a_data_frame(user: User) -> None:
    _live_call()
    response = await user.http_client.get("/api/wall/live-calls/stream?once=true")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert '"calls"' in response.text
