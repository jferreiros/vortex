"""The Postgres call-event store stays off unless both keys are set, and a
``CallLog`` write goes through it and nowhere else.
"""

from __future__ import annotations

from vortex.observability import supabase_log
from vortex.observability.calllog import CallLog
from vortex.settings import reset_settings


def test_event_hash_is_order_independent() -> None:
    a = {"kind": "call.started", "call_id": "C1", "ts": "t"}
    b = {"ts": "t", "call_id": "C1", "kind": "call.started"}
    assert supabase_log.event_hash(a) == supabase_log.event_hash(b)


def test_unconfigured_without_keys(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    reset_settings()
    assert supabase_log.configured() is False
    assert supabase_log.ping()["ok"] is False
    reset_settings()


def test_fetch_calls_is_always_a_pair(monkeypatch) -> None:
    """Callers never branch on ``None``: an unreachable store is an empty
    window, which is what keeps ``GET /calls`` answering at all."""
    monkeypatch.setattr(supabase_log, "fetch_window", lambda **_kw: None)
    grouped, meta = supabase_log.fetch_calls(10)
    assert grouped == {}
    assert meta == {"calls": 0, "events": 0, "truncated": False}


def test_calllog_queues_every_event(_stub_call_events) -> None:
    """The writer has no file to check any more: what it produced is what it
    handed the store."""
    log = CallLog("CA-test")
    log.event("call.started", from_number="+34600000000")
    log.user_turn("hola")
    log.event("call.ended", reason="hangup")

    assert [e["kind"] for e in _stub_call_events] == [
        "call.started",
        "turn.user",
        "call.ended",
    ]
    assert {e["call_id"] for e in _stub_call_events} == {"CA-test"}
    # Queued rows are JSON-safe, so ``event_hash`` is stable over them.
    for event in _stub_call_events:
        assert supabase_log.event_hash(event)


def test_calllog_keeps_its_own_events_and_counters() -> None:
    log = CallLog("CA-counters")
    log.user_turn("quiero una cita")
    log.assistant_turn("claro")
    log.tool_called("find_patient", {"phone": "+34600000000"})
    assert log.turns == 2
    assert log.user_turns == 1
    assert log.tool_calls == 1
    assert log.caller_words() == "quiero una cita"
    assert [e["kind"] for e in log.events] == ["turn.user", "turn.assistant", "tool.called"]


def test_flush_is_a_noop_without_a_store(monkeypatch) -> None:
    """A developer machine with no keys must not raise on hangup."""
    monkeypatch.setattr(supabase_log, "configured", lambda: False)
    log = CallLog("CA-noop")
    log.event("call.started")
    log.flush()  # must not raise
