from datetime import UTC, datetime

import pytest

from vortex.observability.calllog import CallLog, read_recent
from vortex.observability.wall import (
    Phase,
    build_wall_calls,
    group_by_phase,
    historical_stats,
)


def event(kind, call_id="call-1", **data):
    return {"kind": kind, "call_id": call_id, **data}


@pytest.mark.parametrize("phase", list(Phase))
def test_every_explicit_state_has_its_own_group(phase):
    calls = build_wall_calls([event("call.started"), event("call.state", state=phase.value)])
    groups = group_by_phase(calls)
    assert len(groups) == 10
    assert groups[phase] == calls
    assert calls[0].explicit_state
    assert historical_stats(calls).active == (phase != Phase.FINISHED)


@pytest.mark.parametrize(
    ("tool", "phase"),
    [
        ("find_patient", Phase.IDENTIFYING),
        ("build_registration", Phase.REGISTERING),
        ("triage", Phase.ROUTING),
        ("find_slots", Phase.SEARCHING),
        ("prepare_booking", Phase.OFFERING),
        ("list_appointments", Phase.MODIFYING),
        ("prepare_reschedule", Phase.MODIFYING),
        ("prepare_cancel", Phase.MODIFYING),
        ("submit_action", Phase.SUBMITTING),
    ],
)
def test_legacy_tool_events_provide_estimated_states(tool, phase):
    call = build_wall_calls([event("call.started"), event("tool.called", tool=tool)])[0]
    assert call.phase == phase
    assert not call.explicit_state


@pytest.mark.parametrize(
    ("tool", "result", "phase"),
    [
        ("find_patient", {"status": "found"}, Phase.ROUTING),
        ("find_patient", {"status": "ambiguous"}, Phase.IDENTIFYING),
        ("find_patient", {"status": "not_found"}, Phase.REGISTERING),
        ("find_slots", {"slots": [{"start": "2026-09-24T16:30:00+02:00"}]}, Phase.OFFERING),
        ("find_slots", {"slots": []}, Phase.SEARCHING),
        ("triage", {"emergency": True}, Phase.EMERGENCY),
        ("triage", {"rejection": {"reason": "medical_emergency"}}, Phase.EMERGENCY),
    ],
)
def test_tool_results_advance_the_projection(tool, result, phase):
    call = build_wall_calls(
        [event("call.started"), event("tool.returned", tool=tool, result=result)]
    )[0]
    assert call.phase == phase


def test_explicit_state_wins_but_call_closure_is_terminal():
    events = [
        event("call.started"),
        event("call.state", state="EMERGENCY"),
        event("tool.called", tool="find_slots"),
    ]
    assert build_wall_calls(events)[0].phase == Phase.EMERGENCY
    events += [event("call.ended"), event("submit.result", result={"status": "accepted"})]
    call = build_wall_calls(events)[0]
    assert call.phase == Phase.FINISHED
    assert not call.active


def test_invalid_explicit_state_does_not_disable_tool_inference():
    calls = build_wall_calls(
        [
            event("call.started"),
            event("call.state", state="invented"),
            event("tool.called", tool="find_patient"),
        ]
    )
    assert calls[0].phase == Phase.IDENTIFYING
    assert not calls[0].explicit_state


def test_twenty_concurrent_calls_are_counted_once_and_grouped_independently():
    events = []
    for index in range(20):
        call_id = f"call-{index}"
        events += [event("call.started", call_id), event("turn.user", call_id, text="Hola")]
    events += [event("call.ended", "call-0"), event("call.summary", "call-0")]
    events += [event("tool.called", "call-1", tool="find_slots")]
    calls = build_wall_calls(events)
    groups = group_by_phase(calls)
    assert historical_stats(calls).active == 19
    assert len(groups[Phase.FINISHED]) == 1
    assert len(groups[Phase.CONNECTED]) == 18
    assert len(groups[Phase.SEARCHING]) == 1


def test_submit_accepted_is_not_finished_or_a_pass():
    events = [
        event("call.started"),
        event("submit.result", route="/api/v1/submit/book", result={"status": "accepted"}),
    ]
    call = build_wall_calls(events)[0]
    assert call.phase == Phase.SUBMITTING
    assert call.active
    assert historical_stats([call]).completed == 0
    events.append(event("call.ended"))
    stats = historical_stats(build_wall_calls(events))
    assert stats.accepted == 1
    assert stats.outcomes["BOOK"] == 1
    assert stats.evaluated == 0
    assert stats.pass_rate is None


def test_historical_metrics_include_only_finished_calls_and_known_verdicts():
    events = [
        event("call.started", "passed", language="ca-ES"),
        event("call.summary", "passed", duration_ms=60000),
        event("call.verdict", "passed", passed=True),
        event("call.started", "failed"),
        event("language.detected", "failed", language="en"),
        event("call.summary", "failed", duration_ms=120000),
        event("call.verdict", "failed", passed=False),
        event("call.started", "unknown"),
        event("call.ended", "unknown"),
        event("call.started", "active", language="es"),
        event("call.verdict", "active", passed=True),
    ]
    stats = historical_stats(build_wall_calls(events))
    assert stats.active == 1
    assert stats.completed == 3
    assert stats.average_seconds == 90
    assert stats.evaluated == 2
    assert stats.passed == 1
    assert stats.pass_rate == 0.5
    assert stats.languages == {"ca": 1, "en": 1, "Sin detectar": 1}


def test_multiaction_retries_and_summary_do_not_inflate_results():
    book = {"route": "/api/v1/submit/book", "result": {"status": "accepted"}}
    cancel = {"route": "/api/v1/submit/cancel", "result": {"status": "accepted"}}
    calls = build_wall_calls(
        [
            event("call.started"),
            event("submit.result", **book),
            event("submit.result", route=book["route"], result={"status": "duplicate"}),
            event("submit.result", **cancel),
            event("call.summary", actions=[book, cancel]),
        ]
    )
    stats = historical_stats(calls)
    assert stats.outcomes["BOOK"] == 1
    assert stats.outcomes["CANCEL"] == 1
    assert stats.completed == 1
    assert calls[0].result_label == "BOOK + CANCEL"


@pytest.mark.parametrize("status", ["rejected", "error", "late", "unknown_call"])
def test_failed_submissions_are_not_displayed_as_completed_bookings(status):
    calls = build_wall_calls(
        [
            event("call.started"),
            event("submit.result", route="/api/v1/submit/book", result={"status": status}),
            event("call.ended"),
        ]
    )
    stats = historical_stats(calls)
    assert stats.outcomes["BOOK"] == 0
    assert stats.outcomes["SIN RESULTADO"] == 1
    assert stats.accepted == 0


def test_dry_runs_are_simulations_not_accepted_or_passed():
    calls = build_wall_calls(
        [
            event("call.started", voice="demo"),
            event("submit.result", route="/api/v1/submit/book", result={"status": "dry_run"}),
            event("call.ended"),
        ]
    )
    stats = historical_stats(calls)
    assert stats.simulated == 1
    assert stats.accepted == 0
    assert stats.pass_rate is None
    assert stats.outcomes["BOOK"] == 1


def test_preferred_provider_language_is_not_a_detected_caller_language():
    calls = build_wall_calls(
        [
            event("call.started"),
            event("tool.called", tool="find_slots", args={"language": "ca"}),
            event("call.ended"),
        ]
    )
    assert historical_stats(calls).languages == {"Sin detectar": 1}


def test_refusal_reason_and_outcome_are_preserved():
    calls = build_wall_calls(
        [
            event("call.started"),
            event(
                "submit.result",
                route="/api/v1/submit/no-action",
                payload={"reason": "no_availability"},
                result={"status": "accepted"},
            ),
            event("call.ended"),
        ]
    )
    stats = historical_stats(calls)
    assert stats.outcomes["NO_ACTION"] == 1
    assert stats.reasons == {"no_availability": 1}


def test_partial_log_does_not_invent_an_active_socket():
    calls = build_wall_calls([event("tool.called", tool="find_patient")])
    assert historical_stats(calls).active == 0
    assert not any(group_by_phase(calls).values())


def test_live_duration_uses_start_timestamp():
    call = build_wall_calls([event("call.started", ts="2026-09-18T10:00:00+00:00")])[0]
    assert call.duration_seconds(datetime(2026, 9, 18, 10, 2, tzinfo=UTC)) == 120


def test_public_history_is_not_limited_to_last_800_events(tmp_path):
    path = tmp_path / "calls.jsonl"
    for index in range(410):
        log = CallLog(str(index), path)
        log.event("call.started")
        log.event("call.ended")
    calls = build_wall_calls(read_recent(path, limit=0))
    assert historical_stats(calls).completed == 410
    assert historical_stats(calls).active == 0


def test_empty_dashboard_has_no_fabricated_metrics():
    stats = historical_stats([])
    assert stats.active == stats.completed == stats.evaluated == 0
    assert stats.average_seconds is None
    assert stats.pass_rate is None
