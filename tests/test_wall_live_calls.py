"""``/api/wall/live-calls`` — the Live Calls page's real feed.

Replaces the page's ``PLACEHOLDER_CALLS`` mock: a call still in progress
(no ``call.ended`` line yet) shows up here, off the same "recent" feed
every other live card on the board reads (line API first, the hosted
Supabase log as its automatic fallback, this process's JSONL last — see
``vortex.observability.callfeed.load_events``).
"""

from __future__ import annotations

from pathlib import Path

from nicegui.testing import User

from vortex.observability.calllog import CallLog


def _live_call(path: Path, cid: str = "CA-live") -> None:
    log = CallLog(cid, path)
    log.event("call.started", from_number="+34612345678", voice="stub", clinic="fake")
    log.user_turn("Hola, quería pedir cita para mi hija")
    log.tool_called("find_patient", {"name": "Lucía Ruiz López"})
    log.tool_returned("find_patient", {"status": "found", "patient": {"patient_id": "P00001"}}, 30)
    # No call.ended: the card is still open, i.e. `card.live` is True.


def _ended_call(path: Path, cid: str = "CA-done") -> None:
    log = CallLog(cid, path)
    log.event("call.started", from_number="+34600000000", voice="stub", clinic="fake")
    log.user_turn("Quiero cancelar mi cita")
    log.event("call.ended", reason="hangup")
    log.summary(reason="hangup")


async def test_live_calls_lists_only_calls_still_in_progress(
    user: User, offline_settings
) -> None:
    _live_call(Path(offline_settings.calls_log_path))
    _ended_call(Path(offline_settings.calls_log_path))

    response = await user.http_client.get("/api/wall/live-calls")
    assert response.status_code == 200
    calls = response.json()["calls"]

    assert [c["id"] for c in calls] == ["CA-live"]
    live = calls[0]
    assert live["status"] == "live"
    assert live["direction"] == "inbound"
    assert live["phone"] == "+34612345678"
    # find_patient is a "decide"-adjacent identify step; the phase reads
    # past "Listen" once the call has looked the patient up.
    assert live["phase"] != ""


async def test_live_calls_is_empty_with_no_calls_in_progress(
    user: User, offline_settings
) -> None:
    _ended_call(Path(offline_settings.calls_log_path))
    response = await user.http_client.get("/api/wall/live-calls")
    assert response.json()["calls"] == []
