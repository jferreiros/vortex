"""``GET /api/wall/calls/active``: the calls on the line right now.

Every call in the log that never saw a ``call.ended`` shows up with its id,
masked number, stage, best-guess intent, fine-grained phase and the tools it
ran - the row the React wall's Live section draws each call from.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from nicegui.testing import User

from vortex.observability import callfeed
from vortex.observability.calllog import CallLog
from vortex.observability.wall_timeline import call_phase


@pytest.fixture
def feed(offline_settings, monkeypatch: pytest.MonkeyPatch):
    """callfeed with clean source caches, so no earlier test's last-good
    read leaks in as a live line answer."""
    callfeed._last_good.clear()
    callfeed._scope_cache.clear()
    yield callfeed
    callfeed._last_good.clear()
    callfeed._scope_cache.clear()


def _live_call(path: Path, cid: str = "CA-live") -> None:
    log = CallLog(cid, path)
    log.event("call.started", from_number="+34612345678", voice="stub", clinic="fake")
    log.user_turn("quiero anular mi cita")
    log.event("call.intent", intent="cancel", tool="prepare_cancel")
    log.tool_called("prepare_cancel", {"appointment_id": "A0001"})


def _ended_call(path: Path, cid: str = "CA-done") -> None:
    log = CallLog(cid, path)
    log.event("call.started", from_number="+34600000000", voice="stub", clinic="fake")
    log.user_turn("hola")
    log.event("call.ended", reason="hangup")
    log.summary(reason="hangup")


def _stale_call(path: Path, cid: str = "CA-stale") -> None:
    """A call whose socket died before ``call.ended`` was ever written."""
    old = (datetime.now(UTC) - timedelta(seconds=600)).isoformat(timespec="milliseconds")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"ts": old, "call_id": cid, "kind": "call.started"}) + "\n"
        )
        fh.write(json.dumps({"ts": old, "call_id": cid, "kind": "turn.user", "text": "hola"}) + "\n")


async def test_active_calls_lists_only_live_calls(
    feed, user: User, monkeypatch: pytest.MonkeyPatch, offline_settings
) -> None:
    path = Path(offline_settings.calls_log_path)
    _live_call(path)
    _ended_call(path)
    _stale_call(path)

    def boom(*_a: object, **_k: object) -> Any:
        raise OSError("offline")

    monkeypatch.setattr(callfeed.httpx, "get", boom)
    resp = await user.http_client.get("/api/wall/calls/active")
    assert resp.status_code == 200
    rows = resp.json()

    assert [row["call_id"] for row in rows] == ["CA-live"]
    row = rows[0]
    # The number is masked; the raw digits never reach the wall.
    assert "+34612345678" not in json.dumps(rows)
    assert row["from_masked"].endswith("678")
    assert row["from"] == row["from_masked"]
    assert row["started_ts"]
    assert row["intent"] == "cancel"
    assert row["tools_run"] == ["prepare_cancel"]
    assert row["phase"] == "working"  # prepare_cancel is still open
    assert isinstance(row["stage"], int)


# ---------------------------------------------------------------------------
# call_phase: the fine-grained state the wave animates by
# ---------------------------------------------------------------------------


def _phase(events: list[dict[str, Any]], now: datetime | None = None) -> str:
    return call_phase(events, "CA-1", now=now)


def test_call_phase_walks_the_conversation() -> None:
    now = datetime(2026, 9, 19, 10, 0, 0, tzinfo=UTC)
    ts = now.isoformat()
    assert _phase([{"kind": "call.started", "call_id": "CA-1", "ts": ts}], now) == "connecting"
    assert (
        _phase(
            [
                {"kind": "call.started", "call_id": "CA-1", "ts": ts},
                {"kind": "turn.user", "call_id": "CA-1", "ts": ts},
            ],
            now,
        )
        == "thinking"
    )
    assert (
        _phase(
            [
                {"kind": "call.started", "call_id": "CA-1", "ts": ts},
                {"kind": "tool.called", "call_id": "CA-1", "tool": "find_slots", "ts": ts},
            ],
            now,
        )
        == "working"
    )
    # A returned tool leaves the model composing: thinking again.
    assert (
        _phase(
            [
                {"kind": "tool.called", "call_id": "CA-1", "tool": "find_slots", "ts": ts},
                {"kind": "tool.returned", "call_id": "CA-1", "tool": "find_slots", "ts": ts},
            ],
            now,
        )
        == "thinking"
    )


def test_call_phase_speaking_then_listening() -> None:
    now = datetime(2026, 9, 19, 10, 0, 0, tzinfo=UTC)
    events = [
        {"kind": "call.started", "call_id": "CA-1", "ts": now.isoformat()},
        {"kind": "turn.assistant", "call_id": "CA-1", "ts": now.isoformat()},
    ]
    assert _phase(events, now + timedelta(seconds=1)) == "speaking"
    assert _phase(events, now + timedelta(seconds=30)) == "listening"


def test_call_phase_ended_wins() -> None:
    now = datetime(2026, 9, 19, 10, 0, 0, tzinfo=UTC)
    events = [
        {"kind": "call.started", "call_id": "CA-1", "ts": now.isoformat()},
        {"kind": "turn.assistant", "call_id": "CA-1", "ts": now.isoformat()},
        {"kind": "call.ended", "call_id": "CA-1", "ts": now.isoformat()},
    ]
    assert _phase(events, now) == "ended"
    # Other calls' events never bleed in.
    events.append({"kind": "turn.user", "call_id": "CA-2", "ts": now.isoformat()})
    assert _phase(events, now) == "ended"
