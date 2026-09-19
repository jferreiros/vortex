"""How the board ingests the call log — the live-Insights regression.

The live deployment showed every Insights block empty because the board asked
the line for the last 800 *events* (about ten calls out of hundreds, with the
oldest one cut mid-flight so it had no ``call.started``) and, when that fetch
failed, fell back to its own empty log volume. These tests pin the two fixes:
reads bounded by complete calls or by date, and an explicit report of which
source served the data.

``load_events`` lives in ``vortex.observability.callfeed``, a leaf module:
importing it here does not pull in live.py, which matters because NiceGUI's
``user`` tests re-execute live.py via runpy and rely on ``console`` not being
already imported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from nicegui.testing import User
from starlette.testclient import TestClient

from vortex.observability import callfeed
from vortex.observability.calllog import CallLog, group_by_call, read_calls, read_recent


def _write_call(path: Path, cid: str, started: str, events: int = 4) -> None:
    """Append one complete call: a start, filler events, an end."""
    lines = [
        {"ts": started, "call_id": cid, "kind": "call.started", "from_number": "+34600000000"},
    ]
    for i in range(events):
        lines.append({"ts": started, "call_id": cid, "kind": "turn.user", "text": f"hola {i}"})
    lines.append({"ts": started, "call_id": cid, "kind": "call.ended", "reason": "hangup"})
    with path.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def test_read_calls_returns_complete_calls_only(tmp_path: Path) -> None:
    """More than the old 800-event tail: every returned call keeps its start."""
    path = tmp_path / "calls.jsonl"
    for i in range(30):
        _write_call(path, f"CA-{i:03}", f"2026-09-19T10:{i % 60:02d}:00.000+00:00", events=40)
    assert sum(1 for _ in path.open()) > 800  # would already overflow the old tail

    grouped, meta = read_calls(path, max_calls=10)
    assert meta["calls"] == 10
    for cid, events in grouped.items():
        assert events[0]["kind"] == "call.started"
        assert events[0]["call_id"] == cid
    # The newest ten by start time, ordered oldest first.
    assert list(grouped) == [f"CA-{i:03}" for i in range(20, 30)]


def test_read_calls_since_filters_on_call_start(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    _write_call(path, "old", "2026-09-01T10:00:00.000+00:00")
    _write_call(path, "new", "2026-09-19T10:00:00.000+00:00")

    grouped, _meta = read_calls(path, since="2026-09-15T00:00:00+00:00")
    assert set(grouped) == {"new"}

    grouped, _meta = read_calls(path, since="2026-09-19T10:00:00.000+00:00")
    assert set(grouped) == {"new"}  # boundary is inclusive

    grouped, _meta = read_calls(path, since="2026-09-20T00:00:00+00:00")
    assert grouped == {}


def test_read_calls_since_still_finds_a_straddling_start(tmp_path: Path) -> None:
    """A call whose events span the cutoff never arrives half-built: the scan
    continues past the horizon until every in-window group has its start."""
    path = tmp_path / "calls.jsonl"
    lines = [
        {"ts": "2026-09-14T23:59:58.000+00:00", "call_id": "edge", "kind": "call.started"},
        {"ts": "2026-09-15T00:00:01.000+00:00", "call_id": "edge", "kind": "turn.user"},
        {"ts": "2026-09-19T10:00:00.000+00:00", "call_id": "in", "kind": "call.started"},
        {"ts": "2026-09-19T10:00:10.000+00:00", "call_id": "in", "kind": "call.ended"},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

    grouped, _meta = read_calls(path, since="2026-09-15T00:00:00+00:00")
    # "edge" started before the window, so it stays out — and never truncated.
    assert set(grouped) == {"in"}


def test_read_calls_since_and_max_calls_together(tmp_path: Path) -> None:
    """Both bounds at once must not trip on groups seen only past the
    horizon — their start is unknown and they are not needed anyway."""
    path = tmp_path / "calls.jsonl"
    _write_call(path, "old", "2026-09-01T10:00:00.000+00:00")
    for i in range(5):
        _write_call(path, f"CA-{i}", f"2026-09-19T10:0{i}:00.000+00:00")

    grouped, meta = read_calls(path, since="2026-09-15T00:00:00+00:00", max_calls=2)
    assert set(grouped) == {"CA-3", "CA-4"}
    assert meta["calls"] == 2


def test_read_calls_truncation_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    for i in range(10):
        _write_call(path, f"CA-{i}", "2026-09-19T10:00:00.000+00:00", events=10)
    _grouped, meta = read_calls(path, max_events=50)
    assert meta["truncated"] is True


def test_read_calls_unbounded_reads_every_call(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    for i in range(4):
        _write_call(path, f"CA-{i}", f"2026-09-19T10:0{i}:00.000+00:00")
    grouped, meta = read_calls(path)
    assert meta["calls"] == 4
    assert len(grouped) == 4


def test_read_recent_still_reads_the_tail(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    _write_call(path, "one", "2026-09-19T10:00:00.000+00:00", events=10)
    events = read_recent(path, limit=5)
    assert len(events) == 5
    assert events[-1]["kind"] == "call.ended"


# ---------------------------------------------------------------------------
# The line's /calls endpoint
# ---------------------------------------------------------------------------


def test_calls_endpoint_bounds_by_calls_not_events(offline_settings) -> None:
    path = Path(offline_settings.calls_log_path)
    for i in range(5):
        _write_call(path, f"CA-{i}", f"2026-09-19T10:0{i}:00.000+00:00", events=30)

    from vortex.line.server import create_app

    client = TestClient(create_app(offline_settings))
    body = client.get("/calls", params={"calls": 2}).json()
    assert set(body["calls"]) == {"CA-3", "CA-4"}
    assert body["meta"]["calls"] == 2
    assert body["meta"]["truncated"] is False
    for events in body["calls"].values():
        assert events[0]["kind"] == "call.started"


def test_calls_endpoint_since_and_bad_input(offline_settings) -> None:
    path = Path(offline_settings.calls_log_path)
    _write_call(path, "old", "2026-09-01T10:00:00.000+00:00")
    _write_call(path, "new", "2026-09-19T10:00:00.000+00:00")

    from vortex.line.server import create_app

    client = TestClient(create_app(offline_settings))
    body = client.get("/calls", params={"since": "2026-09-10T00:00:00+00:00"}).json()
    assert set(body["calls"]) == {"new"}
    assert client.get("/calls", params={"since": "not-a-date"}).status_code == 400
    # The legacy event tail keeps working for anything still using it.
    assert "calls" in client.get("/calls", params={"limit": 50}).json()


# ---------------------------------------------------------------------------
# load_events: which source served the data
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


@pytest.fixture
def feed(offline_settings, monkeypatch: pytest.MonkeyPatch):
    """callfeed with clean source caches — a leftover last-good entry from
    another test must never be mistaken for a real line read."""
    callfeed._last_good.clear()
    callfeed._scope_cache.clear()
    yield callfeed
    callfeed._last_good.clear()
    callfeed._scope_cache.clear()


def _seeded_call(path: Path, cid: str = "CA-seed") -> None:
    log = CallLog(cid, path)
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


def test_load_events_uses_the_line_when_reachable(feed, monkeypatch, tmp_path) -> None:
    calls_seen: list[dict] = []

    def fake_get(url: str, params: dict | None = None, timeout: float = 0) -> _Resp:
        if url.endswith("/health"):
            return _Resp({"status": "ok", "voice": "stub"})
        calls_seen.append(params or {})
        return _Resp(
            {"calls": {"CA-remote": [{"kind": "call.started", "call_id": "CA-remote", "ts": "t"}]}}
        )

    monkeypatch.setattr(callfeed.httpx, "get", fake_get)
    events, health, source = feed.load_events("recent", tmp_path / "calls.jsonl")
    assert source["kind"] == "line_api"
    assert health["status"] == "ok"
    # Bounded by calls, never by an event tail.
    assert calls_seen[0]["calls"] == feed.WALL_CALLS
    assert "limit" not in calls_seen[0]
    assert events[0]["call_id"] == "CA-remote"


def test_load_events_insights_scope_asks_by_date(feed, monkeypatch, tmp_path) -> None:
    calls_seen: list[dict] = []

    def fake_get(url: str, params: dict | None = None, timeout: float = 0) -> _Resp:
        if url.endswith("/health"):
            return _Resp({"status": "ok"})
        calls_seen.append(params or {})
        return _Resp({"calls": {}})

    from datetime import UTC, datetime

    monkeypatch.setattr(callfeed.httpx, "get", fake_get)
    cutoff = datetime(2026, 9, 1, tzinfo=UTC)
    _events, _health, source = feed.load_events(
        "insights:30", tmp_path / "calls.jsonl", since=cutoff
    )
    assert source["kind"] == "line_api"
    assert calls_seen[0] == {"since": cutoff.isoformat()}


def test_load_events_prefers_hosted_sql_on_recent(feed, monkeypatch, offline_settings) -> None:
    """The live wall reads hosted tables first too — not only dated windows."""
    from vortex.observability import supabase_log

    path = Path(offline_settings.calls_log_path)
    hosted = {
        "CA-hosted": [
            {
                "ts": "2026-09-10T10:00:00.000+00:00",
                "call_id": "CA-hosted",
                "kind": "call.started",
            }
        ]
    }

    def boom(*_a: object, **_k: object) -> _Resp:
        raise AssertionError("recent reads must not hit the line when hosted data is in")

    monkeypatch.setattr(feed.httpx, "get", boom)
    monkeypatch.setattr(supabase_log, "uses_this_log", lambda _path: True)
    monkeypatch.setattr(
        supabase_log,
        "fetch_window",
        lambda **_kw: (hosted, {"calls": 1, "events": 1, "truncated": False}),
    )

    events, health, source = feed.load_events("recent", path)
    assert source["kind"] == "supabase"
    assert health is None
    assert events[0]["call_id"] == "CA-hosted"


def test_load_events_prefers_hosted_sql_on_a_dated_window(
    feed, monkeypatch, offline_settings
) -> None:
    """Home / Insights read the hosted tables first so a board with no
    line volume still paints the same cards the product DB already holds."""
    from vortex.observability import supabase_log

    path = Path(offline_settings.calls_log_path)
    hosted = {
        "CA-hosted": [
            {
                "ts": "2026-09-10T10:00:00.000+00:00",
                "call_id": "CA-hosted",
                "kind": "call.started",
            }
        ]
    }

    def boom(*_a: object, **_k: object) -> _Resp:
        raise AssertionError("dated windows must not hit the line when hosted data is in")

    monkeypatch.setattr(feed.httpx, "get", boom)
    monkeypatch.setattr(supabase_log, "uses_this_log", lambda _path: True)
    monkeypatch.setattr(
        supabase_log,
        "fetch_window",
        lambda **_kw: (hosted, {"calls": 1, "events": 1, "truncated": False}),
    )

    from datetime import UTC, datetime

    events, health, source = feed.load_events(
        "home:90", path, since=datetime(2026, 9, 1, tzinfo=UTC)
    )
    assert source["kind"] == "supabase"
    assert health is None
    assert events[0]["call_id"] == "CA-hosted"


def test_load_events_falls_back_to_the_configured_log(feed, monkeypatch, offline_settings) -> None:
    path = Path(offline_settings.calls_log_path)
    _seeded_call(path)

    def boom(*_a: object, **_k: object) -> _Resp:
        raise OSError("dns: no such host")

    monkeypatch.setattr(callfeed.httpx, "get", boom)
    events, health, source = feed.load_events("recent", path)
    assert source["kind"] == "jsonl_fallback"
    assert "dns" in source["detail"]
    assert health is None
    assert {e["call_id"] for e in events} == {"CA-seed"}


def test_load_events_serves_last_good_on_a_transient_failure(feed, monkeypatch, tmp_path) -> None:
    state = {"up": True}

    def flaky_get(url: str, params: dict | None = None, timeout: float = 0) -> _Resp:
        if not state["up"]:
            raise TimeoutError("read timed out")
        if url.endswith("/health"):
            return _Resp({"status": "ok"})
        return _Resp({"calls": {"CA-1": [{"kind": "call.started", "call_id": "CA-1", "ts": "t"}]}})

    monkeypatch.setattr(callfeed.httpx, "get", flaky_get)
    feed.load_events("recent", tmp_path / "calls.jsonl")
    state["up"] = False
    events, _health, source = feed.load_events("recent", tmp_path / "calls.jsonl")
    assert source["kind"] == "cache"
    assert "timed out" in source["detail"]
    assert events[0]["call_id"] == "CA-1"


def test_load_events_treats_a_bad_response_as_a_failure(
    feed, monkeypatch, offline_settings
) -> None:
    path = Path(offline_settings.calls_log_path)
    _seeded_call(path)

    def weird_get(url: str, **_k: object) -> _Resp:
        if url.endswith("/health"):
            return _Resp({"status": "ok"})
        return _Resp({"calls": ["not", "a", "dict"]})

    monkeypatch.setattr(callfeed.httpx, "get", weird_get)
    _events, _health, source = feed.load_events("recent", path)
    assert source["kind"] == "jsonl_fallback"


def test_cancellation_pack_replays_to_a_full_insights_block(tmp_path: Path) -> None:
    """Generate the pack file, replay it into a live log the way the console
    button does, and the panel shows every status: two rebooked (relocated),
    two past their appointment day (lost), one still open (pending)."""
    import asyncio

    from vortex.observability.business_insights import cancellation_slots
    from vortex.observability.demo import replay_cancellation_demo, write_cancellation_pack
    from vortex.observability.view import build_calls, flatten_grouped

    pack = tmp_path / "cancellation_demo.jsonl"
    asyncio.run(write_cancellation_pack(pack, delay_s=0))

    log_path = tmp_path / "calls.jsonl"
    written = asyncio.run(replay_cancellation_demo(log_path, pack_path=pack, run_tag="t"))
    assert len(written) == 8
    # Replay re-ids every call, so a second run must not merge into the first.
    asyncio.run(replay_cancellation_demo(log_path, pack_path=pack, run_tag="t2"))
    grouped, meta = read_calls(log_path)
    assert meta["calls"] == 16

    out = cancellation_slots(build_calls(flatten_grouped(grouped)))
    assert out["freed_total"] == 10
    assert out["relocated"] == 4
    assert out["lost"] == 4
    assert out["pending"] == 2
    assert out["recovery_rate_pct"] == 50.0
    assert out["daily"] is not None
    assert out["suggested_action"]


# ---------------------------------------------------------------------------
# The real endpoint, inside the NiceGUI simulation
# ---------------------------------------------------------------------------


async def test_business_insights_endpoint_falls_back_and_fills_blocks(
    feed, user: User, monkeypatch: pytest.MonkeyPatch, offline_settings
) -> None:
    """Line unreachable -> the seeded log is read, the buckets fill, and the
    response says where the data came from instead of pretending zeros."""
    path = Path(offline_settings.calls_log_path)
    _seeded_call(path, "CA-1")
    _seeded_call(path, "CA-2")

    def boom(*_a: object, **_k: object) -> _Resp:
        raise OSError("offline")

    monkeypatch.setattr(callfeed.httpx, "get", boom)
    resp = await user.http_client.get("/api/wall/business-insights?days=30")
    assert resp.status_code == 200
    body = resp.json()

    assert body["range_days"] == 30
    # A value between the pills clamps to the nearest supported window.
    clamped = await user.http_client.get("/api/wall/business-insights?days=45")
    assert clamped.json()["range_days"] == 30
    assert body["source"]["kind"] == "jsonl_fallback"
    assert body["source"]["calls"] == 2
    assert body["calls_considered"] == 2
    assert body["unavailability"]["unmet_total"] == 2
    assert body["unavailability"]["buckets"][0]["key"] == "no_slot_in_window"
    assert body["providers"]["providers"][0]["requests"] == 2


async def test_business_insights_endpoint_reads_the_line_when_up(
    feed, user: User, monkeypatch: pytest.MonkeyPatch, offline_settings
) -> None:
    path = Path(offline_settings.calls_log_path)
    _seeded_call(path, "CA-live")
    grouped = group_by_call(
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    )

    def fake_get(url: str, params: dict | None = None, timeout: float = 0) -> _Resp:
        if url.endswith("/health"):
            return _Resp({"status": "ok", "voice": "stub"})
        return _Resp({"calls": grouped})

    monkeypatch.setattr(callfeed.httpx, "get", fake_get)
    resp = await user.http_client.get("/api/wall/business-insights?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"]["kind"] == "line_api"
    assert body["calls_considered"] == 1
