from __future__ import annotations

from vortex.contract import ALL_REASONS
from vortex.observability.explain import (
    ACTION_LABEL,
    EVENT_TEXT,
    LIVE_SUB,
    REASON_TEXT,
    STAGES,
    TOOL_TEXT,
    event_detail,
    event_text,
    featured_call,
    is_lifecycle,
    outcome_text,
    outcome_title,
    payload_rows,
    stage_of,
    stats_for,
    status_label,
    step_text,
    tool_endpoint,
    wall_sub,
    workflow_beats,
)
from vortex.observability.view import CallCard, ToolStep, Turn


def _booked() -> CallCard:
    card = CallCard(call_id="CA-1", ended=True, duration_ms=42000)
    card.turns = [Turn("assistant", "Hola"), Turn("user", "Cita")]
    card.tools = [
        ToolStep("find_patient", status="ok", ms=40.0, result={"status": "found", "patient": {}}),
        ToolStep("find_slots", status="ok", ms=50.0, result={"slots": [{"start": "x"}]}),
    ]
    card.action_kind = "book"
    card.action_payload = {"call_id": "CA-1", "slot": "x", "patient_id": "P1"}
    card.submit_status = "accepted"
    card.patient_name = "Marta Ruiz"
    card.provider_name = "Dra. Ortiz"
    card.slot = "19/09 10:15"
    return card


def test_every_contract_reason_has_a_sentence() -> None:
    missing = [r for r in ALL_REASONS if r not in REASON_TEXT]
    assert not missing


def test_stage_progresses_with_evidence() -> None:
    assert stage_of(None) == 0
    card = CallCard(call_id="x")
    assert stage_of(card) == 0
    card.turns.append(Turn("user", "hi"))
    assert stage_of(card) == 1
    card.tools.append(ToolStep("find_patient"))
    assert stage_of(card) == 2
    card.tools.append(ToolStep("find_slots"))
    assert stage_of(card) == 3
    card.submit_status = "accepted"
    assert stage_of(card) == 4


def test_outcome_sentences() -> None:
    card = _booked()
    assert outcome_title(card) == "Booked"
    assert "Marta Ruiz" in outcome_text(card)
    assert "Dra. Ortiz" in outcome_text(card)
    refused = CallCard(call_id="r", ended=True, action_kind="no-action", submit_status="dry_run")
    refused.decline_reason = "specialty_not_covered"
    assert outcome_title(refused) == "No action"
    assert "insurance" in outcome_text(refused)
    assert outcome_title(None) == "Waiting for a call"
    # A prepared action that never reached the platform is not an outcome.
    unsent = CallCard(call_id="u", ended=True, action_kind="book")
    assert outcome_title(unsent) == "Ended without a submission"
    assert "never" in outcome_text(unsent) or "before it was sent" in outcome_text(unsent)
    assert status_label(unsent) == "Ended"
    assert status_label(card) == "Booked"


def test_step_text_reads_results() -> None:
    step = ToolStep(
        "check_eligibility",
        status="ok",
        result={"allowed": False, "rejection": {"reason": "referral_required", "detail": "d"}},
    )
    assert "referral" in step_text(step)
    assert "Rejected" in step_text(step)
    assert step_text(ToolStep("find_slots", status="ok", result={"slots": []})).startswith(
        "No slot"
    )
    assert step_text(ToolStep("x", status="fail", error="boom")) == "Failed: boom"


def test_stats_and_payload_rows() -> None:
    card = _booked()
    live = CallCard(call_id="live")
    live.turns.append(Turn("user", "..."))
    stats = stats_for([card, live])
    assert stats.calls == 2
    assert stats.live == 1
    assert stats.booked == 1
    assert stats.submitted == 1
    assert stats.submit_rate == 1.0
    assert stats.median_duration_s == 42.0
    assert stats.median_tool_ms == 45.0
    rows = payload_rows(card)
    assert rows[0][0] == "patient_id"
    assert all(k != "call_id" for k, _ in rows)


def test_tool_endpoint_names_the_clinic_route() -> None:
    assert tool_endpoint("find_slots") == "GET /api/v1/availability"
    assert tool_endpoint("not_a_tool") is None


def test_lifecycle_events_are_the_socket_the_submission_and_the_summary() -> None:
    assert is_lifecycle({"kind": "call.started"})
    assert is_lifecycle({"kind": "submit.result"})
    assert not is_lifecycle({"kind": "turn.user"})
    assert not is_lifecycle({"kind": "tool.returned"})


def test_event_text_says_what_happened_and_event_detail_says_the_facts() -> None:
    ended = {"kind": "call.ended", "reason": "hangup", "media_frames_in": 3, "media_frames_out": 5}
    assert event_text(ended) == "The socket closed."
    assert event_detail(ended) == "reason hangup · frames in 3, out 5"
    submitted = {
        "kind": "submit.result",
        "route": "/api/v1/submit/book",
        "result": {"status": "submitted", "http_status": 200},
    }
    assert event_text(submitted) == "The platform answered the submission."
    assert (
        event_detail(submitted) == "route /api/v1/submit/book · status submitted · http_status 200"
    )
    assert event_text({"kind": "socket.odd"}) == "Socket odd"
    assert event_detail({"kind": "socket.odd"}) == ""


def test_screen_words_say_patient_never_caller() -> None:
    blob = " ".join(
        [
            *REASON_TEXT.values(),
            *TOOL_TEXT.values(),
            *(text for _, _, text in STAGES),
            *EVENT_TEXT.values(),
            *ACTION_LABEL.values(),
            LIVE_SUB,
            wall_sub("Clínica Arenal"),
        ]
    )
    assert "caller" not in blob.lower()
    assert "patient" in blob.lower()


def test_featured_call_skips_an_empty_stale_socket() -> None:
    greeting = CallCard(call_id="empty", ended=True, from_number="+1")
    greeting.turns.append(Turn("assistant", "Clínica Arenal, buenos días."))
    booked = _booked()
    assert featured_call([greeting, booked]) is booked
    assert featured_call([booked, greeting]) is booked
    live = CallCard(call_id="live")
    live.turns.append(Turn("user", "hola"))
    assert featured_call([booked, live]) is live


def test_workflow_beats_follow_the_line_and_pulse_the_speaker() -> None:
    card = CallCard(call_id="CA-w", from_number="+34600")
    card.events = [
        {"kind": "call.started", "ts": "t0", "from_number": "+34600"},
        {"kind": "turn.assistant", "ts": "t1", "text": "Clínica Arenal, buenos días."},
        {"kind": "turn.user", "ts": "t2", "text": "Quiero una cita."},
        {"kind": "tool.called", "ts": "t3", "tool": "find_patient", "args": {"name": "Marta"}},
        {
            "kind": "tool.returned",
            "ts": "t4",
            "tool": "find_patient",
            "ms": 12,
            "result": {
                "status": "found",
                "patient": {"given_name": "Marta", "first_surname": "Ruiz", "patient_id": "P1"},
            },
        },
        {"kind": "turn.assistant", "ts": "t5", "text": "Marta, ¿para cuándo?"},
    ]
    card.turns = [
        Turn("assistant", "Clínica Arenal, buenos días.", "t1"),
        Turn("user", "Quiero una cita.", "t2"),
        Turn("assistant", "Marta, ¿para cuándo?", "t5"),
    ]
    card.tools = [
        ToolStep(
            "find_patient",
            status="ok",
            ms=12,
            result={
                "status": "found",
                "patient": {"given_name": "Marta", "first_surname": "Ruiz", "patient_id": "P1"},
            },
        )
    ]
    beats = workflow_beats(card)
    kinds = [beat.kind for beat in beats]
    assert kinds == ["start", "agent", "patient", "tool", "agent"]
    tool = next(beat for beat in beats if beat.kind == "tool")
    assert tool.title.startswith("Look the patient")
    assert "Marta" in tool.text
    assert tool.tool == "find_patient"
    assert beats[-1].speaking is True
    assert beats[-1].kind == "agent"
    card.ended = True
    card.action_kind = "book"
    card.submit_status = "accepted"
    card.patient_name = "Marta Ruiz"
    ended = workflow_beats(card)
    assert ended[-1].kind == "outcome"
    assert ended[-1].title == "Booked"
    assert all(not beat.speaking for beat in ended)
