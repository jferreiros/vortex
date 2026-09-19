"""The end-of-call fallback: what a call submits when nobody submitted anything.

Every test runs offline. The submitters here are fakes: the dry-run client the
session builds with no ``PLATFORM_API_KEY``, and two stand-ins below that answer
200 or hang. No sockets, no network, no keys.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from vortex.contract import (
    MADRID,
    Action,
    AvailabilityResult,
    BlockedProvider,
    BookAction,
    BookingResult,
    EligibilityVerdict,
    NoAction,
    Rejection,
    Slot,
    SubmitResult,
    TriageResult,
    action_payload,
    action_route,
)
from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload

NOW = datetime(2026, 9, 18, 10, 0, tzinfo=MADRID)
SLOT = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)


# --- fakes -------------------------------------------------------------------


class AcceptingSubmitter:
    """A submit client the platform always answers 200 to."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="accepted", http_status=200)

    async def aclose(self) -> None:
        return None


class HangingSubmitter:
    """A submit client that never answers. Stands in for a dead platform."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        return None


# --- helpers -----------------------------------------------------------------


def make_session(settings, call_id: str = "CA-fallback") -> CallSession:
    start = StartPayload(streamSid=f"MZ-{call_id}", callSid=call_id, customParameters={})
    return CallSession.open(start, settings=settings, now=NOW)


def sent(session: CallSession) -> list[tuple[str, dict[str, Any]]]:
    """What the call's submit client was handed, in order."""
    return list(session.submitter.sent)  # type: ignore[attr-defined]


def events(settings, call_id: str, kind: str) -> list[dict[str, Any]]:
    path = Path(settings.calls_log_path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return [x for x in lines if x["call_id"] == call_id and x["kind"] == kind]


def a_slot() -> Slot:
    return Slot(
        start=SLOT,
        provider_id="PR05",
        location_id="sur",
        appointment_type_id="review",
    )


def a_booking() -> BookAction:
    return BookAction(
        patient_id="P00042",
        provider_id="PR05",
        location_id="sur",
        appointment_type_id="review",
        slot=SLOT,
        policy_id="sanitas",
    )


# --- branch (c): nobody said a word ------------------------------------------


async def test_a_silent_call_ends_on_out_of_scope(offline_settings) -> None:
    session = make_session(offline_settings, "CA-silent")
    await session.close()

    assert [route for route, _ in sent(session)] == ["/api/v1/submit/no-action"]
    assert sent(session)[0][1]["reason"] == "out_of_scope"
    (event,) = events(offline_settings, "CA-silent", "submit.fallback")
    assert event["branch"] == "no_turns"
    assert event["skipped"] is False
    assert event["why"]


# --- branch (d): a conversation that resolved nothing ------------------------


async def test_a_conversation_that_resolved_nothing_ends_on_out_of_scope(
    offline_settings,
) -> None:
    session = make_session(offline_settings, "CA-default")
    session.ctx.log.user_turn("hola, llamaba por una cita")
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "out_of_scope"
    (event,) = events(offline_settings, "CA-default", "submit.fallback")
    assert event["branch"] == "default"


# --- branch (b): the last rule that bit ---------------------------------------


async def test_the_last_rejection_names_the_rule(offline_settings) -> None:
    session = make_session(offline_settings, "CA-rule")
    session.ctx.log.user_turn("quiero cita con el dermatologo")
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(
            allowed=False,
            rejection=Rejection(reason="referral_required", detail="dermatology needs one"),
        ),
    )
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "referral_required"
    (event,) = events(offline_settings, "CA-rule", "submit.fallback")
    assert event["branch"] == "last_rejection"
    assert "check_eligibility" in event["why"]


async def test_a_red_flag_escalates_instead_of_refusing(offline_settings) -> None:
    session = make_session(offline_settings, "CA-flag")
    session.ctx.log.user_turn("me duele el pecho")
    session.memory.observe(
        "triage",
        TriageResult(emergency=True, rejection=Rejection(reason="medical_emergency")),
    )
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/escalate"
    assert payload["reason"] == "medical_emergency"


async def test_a_blocked_provider_is_a_reason(offline_settings) -> None:
    """find_slots reports the rule that blocked a provider without refusing."""
    session = make_session(offline_settings, "CA-blocked")
    session.ctx.log.user_turn("con la doctora Cid")
    session.memory.observe(
        "find_slots",
        AvailabilityResult(
            slots=[],
            blocked=[BlockedProvider(provider_id="PR05", reason="provider_on_leave")],
        ),
    )
    await session.close()

    assert sent(session)[0][1]["reason"] == "provider_on_leave"


async def test_free_slots_drop_an_earlier_rejection(offline_settings) -> None:
    session = make_session(offline_settings, "CA-cleared")
    session.ctx.log.user_turn("el martes")
    session.memory.observe(
        "find_slots", AvailabilityResult(rejection=Rejection(reason="no_availability"))
    )
    session.memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    await session.close()

    assert session.memory.last_rejection is None
    assert sent(session)[0][1]["reason"] == "out_of_scope"


# --- branch (a): an action prepared and never sent ----------------------------


async def test_an_unconfirmed_prepared_action_is_not_sent(offline_settings) -> None:
    """We do not book a slot the caller never agreed to."""
    session = make_session(offline_settings, "CA-unconfirmed")
    session.ctx.log.user_turn("el jueves por la tarde")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "out_of_scope"
    assert events(offline_settings, "CA-unconfirmed", "submit.fallback")[0]["branch"] == "default"


async def test_a_confirmed_prepared_action_is_sent(offline_settings) -> None:
    session = make_session(offline_settings, "CA-confirmed")
    session.ctx.log.user_turn("si, ese me va bien")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    session.ctx.memory.mark_confirmed()  # the hook the conversation lane calls
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/book"
    assert payload["patient_id"] == "P00042"
    assert payload["slot"].startswith("2026-09-24T16:30")
    event = events(offline_settings, "CA-confirmed", "submit.fallback")[0]
    assert event["branch"] == "prepared"
    assert "confirmed=True" in event["why"]


async def test_a_later_rejection_drops_the_prepared_action(offline_settings) -> None:
    session = make_session(offline_settings, "CA-late-rule")
    session.ctx.log.user_turn("con mi seguro")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    session.ctx.memory.mark_confirmed()
    session.memory.observe(
        "prepare_booking", BookingResult(rejection=Rejection(reason="allowance_exhausted"))
    )
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "allowance_exhausted"
    assert session.memory.prepared is None
    assert session.memory.confirmed is False


def test_a_different_prepared_action_clears_confirmation() -> None:
    """Confirming A must not let the fallback treat a later-prepared B as agreed."""
    memory = CallMemory()
    memory.remember_prepared("prepare_booking", a_booking())
    memory.mark_confirmed()
    other = a_booking().model_copy(update={"slot": SLOT.replace(hour=17)})
    memory.remember_prepared("prepare_booking", other)

    assert memory.confirmed is False
    assert memory.prepared == other


def test_repreparing_the_same_action_keeps_confirmation() -> None:
    """The caller often says yes before the model draws the same plan up again."""
    memory = CallMemory()
    memory.remember_prepared("prepare_booking", a_booking())
    memory.mark_confirmed()
    memory.remember_prepared("prepare_booking", a_booking())

    assert memory.confirmed is True
    assert memory.prepared == a_booking()


# --- what stops the fallback --------------------------------------------------


async def test_a_dry_run_is_not_an_accepted_submission(offline_settings) -> None:
    """Fake mode sends nothing, so the fallback still gets its turn and is logged."""
    session = make_session(offline_settings, "CA-dry")
    await session.submit(NoAction(reason="no_availability"))
    assert session.has_accepted_submission is False

    await session.close()

    assert [route for route, _ in sent(session)] == [
        "/api/v1/submit/no-action",
        "/api/v1/submit/no-action",
    ]
    assert events(offline_settings, "CA-dry", "submit.fallback")[0]["skipped"] is False


async def test_the_fallback_retries_an_unaccepted_action(offline_settings) -> None:
    """A prior send that never landed (dry_run / error) must not skip the fallback."""
    session = make_session(offline_settings, "CA-repeat")
    await session.submit(NoAction(reason="out_of_scope"))

    await session.close()

    assert len(sent(session)) == 2
    event = events(offline_settings, "CA-repeat", "submit.fallback")[0]
    assert event["skipped"] is False
    assert event["retrying"] is True
    assert event["branch"] == "no_turns"


async def test_an_accepted_submission_stops_the_fallback(offline_settings) -> None:
    session = make_session(offline_settings, "CA-accepted")
    submitter = AcceptingSubmitter()
    session.submitter = session.ctx.submitter = submitter
    await session.submit(NoAction(reason="no_availability"))
    assert session.has_accepted_submission is True

    await session.close()

    assert len(submitter.sent) == 1
    assert events(offline_settings, "CA-accepted", "submit.fallback") == []


async def test_the_models_own_submission_counts_as_the_calls_submission(
    offline_settings,
) -> None:
    """submit_action goes through ctx.submitter; the session has to see it anyway."""
    session = make_session(offline_settings, "CA-model")
    submitter = AcceptingSubmitter()
    session.submitter = session.ctx.submitter = submitter

    result = await session.call_tool(
        "submit_action", {"action": {"kind": "no-action", "reason": "no_availability"}}
    )

    assert isinstance(result, SubmitResult)
    assert session.has_accepted_submission is True
    await session.close()
    assert len(submitter.sent) == 1
    assert events(offline_settings, "CA-model", "submit.fallback") == []


# --- the wrap around the registry ---------------------------------------------


async def test_call_tool_remembers_what_a_real_tool_refused(offline_settings) -> None:
    """Nothing in the lane tools knows about the memory; the session wraps them."""
    session = make_session(offline_settings, "CA-wrap")
    session.ctx.log.user_turn("me duele el pecho y no puedo respirar")

    await session.call_tool("triage", {"complaint": "me duele el pecho y no puedo respirar"})

    assert session.memory.last_rejection is not None
    assert session.memory.last_rejection.reason == "medical_emergency"
    await session.close()
    assert sent(session)[0][0] == "/api/v1/submit/escalate"


# --- the 30-second window -----------------------------------------------------


def test_the_window_numbers_are_unchanged(offline_settings) -> None:
    assert offline_settings.submit_window_secs == 30.0
    assert offline_settings.submit_deadline_margin_secs == 5.0


@pytest.mark.parametrize("window,margin", [(0.4, 0.1)])
async def test_the_fallback_gives_up_inside_the_window(
    offline_settings, window: float, margin: float
) -> None:
    """close() waits window - margin for the submission, then logs and moves on."""
    settings = dataclasses.replace(
        offline_settings, submit_window_secs=window, submit_deadline_margin_secs=margin
    )
    session = make_session(settings, "CA-slow")
    session.submitter = session.ctx.submitter = HangingSubmitter()

    started = time.monotonic()
    await session.close()
    elapsed = time.monotonic() - started

    assert window - margin <= elapsed < 5.0
    assert events(settings, "CA-slow", "submit.fallback_timed_out")
    # The summary is still written: a timed-out fallback must not lose the call.
    assert events(settings, "CA-slow", "call.summary")
