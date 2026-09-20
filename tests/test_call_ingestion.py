"""How the board ingests call events — the live-Insights regression.

The live deployment showed every Insights block empty because the board asked
for the last 800 *events* (about ten calls out of hundreds, with the oldest
one cut mid-flight so it had no ``call.started``). These tests pin the fix:
reads bounded by complete calls or by date, out of the one store, and an
explicit report of which source served the data.

``load_events`` lives in ``vortex.observability.callfeed``, a leaf module:
importing it here does not pull in live.py, which matters because NiceGUI's
``user`` tests re-execute live.py via runpy and rely on ``console`` not being
already imported.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from nicegui.testing import User
from starlette.testclient import TestClient

from vortex.observability import callfeed, supabase_log
from vortex.observability.calllog import CallLog, group_by_call


def _call(cid: str, started: str, events: int = 4) -> list[dict[str, Any]]:
    """One complete call: a start, filler events, an end."""
    rows = [{"ts": started, "call_id": cid, "kind": "call.started", "from_number": "+34600000000"}]
    for i in range(events):
        rows.append({"ts": started, "call_id": cid, "kind": "turn.user", "text": f"hola {i}"})
    rows.append({"ts": started, "call_id": cid, "kind": "call.ended", "reason": "hangup"})
    return rows


def _window(*calls: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    grouped = {events[0]["call_id"]: events for events in calls}
    return grouped, {"calls": len(grouped), "events": sum(map(len, calls)), "truncated": False}


# ---------------------------------------------------------------------------
# group_by_call, the one grouping helper left
# ---------------------------------------------------------------------------


def test_group_by_call_keeps_write_order() -> None:
    events = _call("CA-1", "2026-09-19T10:00:00.000+00:00") + _call(
        "CA-2", "2026-09-19T10:01:00.000+00:00"
    )
    grouped = group_by_call(events)
    assert set(grouped) == {"CA-1", "CA-2"}
    assert grouped["CA-1"][0]["kind"] == "call.started"
    assert grouped["CA-1"][-1]["kind"] == "call.ended"


# ---------------------------------------------------------------------------
# The line's /calls endpoint
# ---------------------------------------------------------------------------


def test_calls_endpoint_bounds_by_calls_not_events(offline_settings, monkeypatch) -> None:
    asked: list[tuple[Any, Any]] = []

    def fake_fetch(limit=None, since=None):
        asked.append((limit, since))
        return _window(
            _call("CA-3", "2026-09-19T10:03:00.000+00:00"),
            _call("CA-4", "2026-09-19T10:04:00.000+00:00"),
        )

    monkeypatch.setattr(supabase_log, "fetch_calls", fake_fetch)

    from vortex.line.server import create_app

    client = TestClient(create_app(offline_settings))
    body = client.get("/calls", params={"calls": 2}).json()
    assert set(body["calls"]) == {"CA-3", "CA-4"}
    assert body["meta"]["calls"] == 2
    # Counted in calls, never in an event tail.
    assert asked[0] == (2, None)
    for events in body["calls"].values():
        assert events[0]["kind"] == "call.started"


def test_calls_endpoint_since_and_bad_input(offline_settings, monkeypatch) -> None:
    asked: list[tuple[Any, Any]] = []

    def fake_fetch(limit=None, since=None):
        asked.append((limit, since))
        return _window(_call("new", "2026-09-19T10:00:00.000+00:00"))

    monkeypatch.setattr(supabase_log, "fetch_calls", fake_fetch)
    monkeypatch.setattr(supabase_log, "fetch_recent", lambda _limit: [])

    from vortex.line.server import create_app

    client = TestClient(create_app(offline_settings))
    body = client.get("/calls", params={"since": "2026-09-10T00:00:00+00:00"}).json()
    assert set(body["calls"]) == {"new"}
    assert asked[0][1] == datetime(2026, 9, 10, tzinfo=UTC)
    assert client.get("/calls", params={"since": "not-a-date"}).status_code == 400
    # The legacy event tail keeps working for anything still using it.
    assert client.get("/calls", params={"limit": 50}).json() == {"calls": {}}


def test_health_reports_the_store(offline_settings) -> None:
    from vortex.line.server import create_app

    client = TestClient(create_app(offline_settings))
    assert client.get("/health").json()["store"] == "none"


# ---------------------------------------------------------------------------
# load_events: which source served the data
# ---------------------------------------------------------------------------


@pytest.fixture
def feed(offline_settings, monkeypatch: pytest.MonkeyPatch):
    """callfeed with clean source caches — a leftover last-good entry from
    another test must never be mistaken for a fresh read."""
    callfeed._last_good.clear()
    callfeed._scope_cache.clear()
    yield callfeed
    callfeed._last_good.clear()
    callfeed._scope_cache.clear()


def _seeded_call(cid: str = "CA-seed") -> list[dict[str, Any]]:
    """A whole no-availability call, written through the real ``CallLog`` so
    the shapes the insights panels parse are the ones the line produces."""
    log = CallLog(cid)
    log.event("call.started", from_number="+34600000000", voice="stub", clinic="fake")
    log.user_turn("quiero una cita con la dra ortiz")
    log.tool_called("find_slots", {"date_from": "2026-09-20"})
    log.tool_returned("find_slots", {"slots": [], "rejection": {"reason": "no_availability"}}, 4.0)
    log.action_submitted(
        "/api/v1/submit/no-action",
        {"call_id": cid, "reason": "no_availability"},
        {"status": "dry_run"},
    )
    log.event("call.ended", reason="hangup")
    log.summary(reason="hangup")
    return log.events


def test_load_events_reads_the_store_bounded_by_calls(feed, monkeypatch) -> None:
    asked: list[dict[str, Any]] = []

    def fake_fetch(limit=None, since=None):
        asked.append({"limit": limit, "since": since})
        return _window(_call("CA-store", "2026-09-19T10:00:00.000+00:00"))

    monkeypatch.setattr(supabase_log, "fetch_calls", fake_fetch)
    events, health, source = feed.load_events("recent")
    assert source["kind"] == "supabase"
    assert source["store"] == "supabase"
    assert health is None
    assert asked[0] == {"limit": feed.WALL_CALLS, "since": None}
    assert events[0]["call_id"] == "CA-store"


def test_load_events_insights_scope_asks_by_date(feed, monkeypatch) -> None:
    asked: list[dict[str, Any]] = []

    def fake_fetch(limit=None, since=None):
        asked.append({"limit": limit, "since": since})
        return {}, {"calls": 0, "events": 0, "truncated": False}

    monkeypatch.setattr(supabase_log, "fetch_calls", fake_fetch)
    cutoff = datetime(2026, 9, 1, tzinfo=UTC)
    _events, _health, source = feed.load_events("insights:30", since=cutoff, max_calls=200)
    assert asked[0] == {"limit": 200, "since": cutoff}
    assert source["kind"] == "empty"


def test_load_events_serves_last_good_on_a_transient_failure(feed, monkeypatch) -> None:
    state = {"up": True}

    def flaky(limit=None, since=None):
        if not state["up"]:
            raise TimeoutError("read timed out")
        return _window(_call("CA-1", "2026-09-19T10:00:00.000+00:00"))

    monkeypatch.setattr(supabase_log, "fetch_calls", flaky)
    feed.load_events("recent")
    state["up"] = False
    events, _health, source = feed.load_events("recent")
    assert source["kind"] == "cache"
    assert "timed out" in source["detail"]
    assert events[0]["call_id"] == "CA-1"


def test_load_events_is_empty_not_wrong_when_the_store_is_cold(feed, monkeypatch) -> None:
    """No store and no cache is an honest zero, never a stale other-scope read."""
    monkeypatch.setattr(
        supabase_log, "fetch_calls", lambda *_a, **_k: ({}, {"calls": 0, "events": 0})
    )
    events, _health, source = feed.load_events("recent")
    assert events == []
    assert source["kind"] == "empty"
    assert source["calls"] == 0


# ---------------------------------------------------------------------------
# The real endpoint, inside the NiceGUI simulation
# ---------------------------------------------------------------------------


async def test_business_insights_endpoint_fills_blocks_from_the_store(
    feed, user: User, monkeypatch: pytest.MonkeyPatch, offline_settings
) -> None:
    """Events out of ``call_events`` fill the buckets, and the response says
    where the data came from instead of pretending zeros."""
    grouped = {cid: _seeded_call(cid) for cid in ("CA-1", "CA-2")}
    monkeypatch.setattr(
        supabase_log,
        "fetch_calls",
        lambda *_a, **_k: (grouped, {"calls": 2, "events": 14, "truncated": False}),
    )

    resp = await user.http_client.get("/api/wall/business-insights?days=30")
    assert resp.status_code == 200
    body = resp.json()

    assert body["range_days"] == 30
    # A value between the pills clamps to the nearest supported window.
    clamped = await user.http_client.get("/api/wall/business-insights?days=45")
    assert clamped.json()["range_days"] == 30
    assert body["source"]["kind"] == "supabase"
    assert body["source"]["calls"] == 2
    assert body["calls_considered"] == 2
    assert body["unavailability"]["unmet_total"] == 2
    assert body["unavailability"]["buckets"][0]["key"] == "no_slot_in_window"
    assert body["providers"]["providers"][0]["requests"] == 2
