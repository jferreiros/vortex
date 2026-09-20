from __future__ import annotations

from vortex.observability.calllog import CallLog
from vortex.observability.view import build_call, build_calls


def test_build_call_pairs_tools_and_booking() -> None:
    log = CallLog("CA-1")
    log.event("call.started", from_number="+34600", voice="stub", clinic="fake")
    log.user_turn("Quiero una revisión")
    log.tool_called("find_patient", {"name": "Marta"})
    log.tool_returned(
        "find_patient",
        {
            "status": "found",
            "patient": {
                "patient_id": "P00042",
                "given_name": "Marta",
                "first_surname": "Ruiz",
                "second_surname": "López",
            },
        },
        12.0,
    )
    log.tool_called("prepare_booking", {"patient_id": "P00042"})
    log.tool_returned(
        "prepare_booking",
        {
            "action": {
                "kind": "book",
                "slot": "2026-09-19T10:15:00+02:00",
                "provider_id": "PR01",
            }
        },
        4.0,
    )
    log.action_submitted(
        "/api/v1/submit/book",
        {"call_id": "CA-1", "patient_id": "P00042"},
        {"status": "dry_run"},
    )
    log.event("call.ended", reason="hangup")
    log.summary(reason="hangup")

    card = build_call("CA-1", log.events)
    assert card.live is False
    assert card.status == "booked"
    assert card.patient_name == "Marta Ruiz López"
    assert card.patient_id == "P00042"
    assert card.slot == "19/09 10:15"
    assert card.tools[0].status == "ok"
    assert card.tools[0].ms == 12.0
    assert card.submit_status == "dry_run"
    assert card.action_kind == "book"


def test_live_call_without_end() -> None:
    events = [
        {"kind": "call.started", "call_id": "CA-2", "from_number": "+1"},
        {"kind": "tool.called", "call_id": "CA-2", "tool": "triage", "args": {}},
    ]
    card = build_call("CA-2", events)
    assert card.live is True
    assert card.status == "live"
    assert card.tools[0].status == "running"


def test_refuse_reason_from_eligibility() -> None:
    events = [
        {"kind": "call.started", "call_id": "CA-3"},
        {
            "kind": "tool.returned",
            "call_id": "CA-3",
            "tool": "check_eligibility",
            "result": {"allowed": False, "rejection": {"reason": "not_eligible_age"}},
            "ms": 3,
        },
        {
            "kind": "submit.result",
            "call_id": "CA-3",
            "route": "/api/v1/submit/no-action",
            "payload": {"reason": "not_eligible_age"},
            "result": {"status": "accepted"},
        },
        {"kind": "call.ended", "call_id": "CA-3", "reason": "hangup"},
    ]
    card = build_call("CA-3", events)
    assert card.status == "refused"
    assert card.decline_reason == "not_eligible_age"


def test_turn_time_renders_the_madrid_clock() -> None:
    """The regression: a workflow card showed the host machine's clock.

    ``_turn_time`` converts to Europe/Madrid explicitly, so a UTC timestamp
    renders as the Madrid wall clock whatever timezone the host runs in. This
    is asserted directly rather than through ``time.tzset``, which is Unix-only.
    """
    from vortex.observability.live import _turn_time

    card = build_call(
        "CA-4",
        [{"kind": "call.started", "call_id": "CA-4", "ts": "2026-09-19T08:00:00+00:00"}],
    )
    assert _turn_time(card, "2026-09-19T08:00:30+00:00") == "10:00:30 +30.0s"


def test_build_calls_newest_first() -> None:
    events = [
        {"kind": "call.started", "call_id": "A", "ts": "1"},
        {"kind": "call.ended", "call_id": "A", "ts": "2"},
        {"kind": "call.started", "call_id": "B", "ts": "3"},
    ]
    cards = build_calls(events)
    assert [c.call_id for c in cards] == ["B", "A"]
    assert cards[0].live is True
    assert cards[1].live is False
