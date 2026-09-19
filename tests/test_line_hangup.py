"""Hanging up from our side once the platform holds an action.

Every call used to run until the harness cut it at three minutes, booked calls
included. Now an accepted ``submit_action`` arms the session and the pipeline
ends itself after the agent's farewell — or one idle period later if the model
submits and then says nothing.

Offline. The submit clients here are fakes and the pipeline is never built: the
watcher is driven with the frames the output transport would have pushed.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from vortex.contract import (
    MADRID,
    Action,
    EligibilityVerdict,
    NoAction,
    Rejection,
    SubmitResult,
    action_route,
)
from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload

NOW = datetime(2026, 9, 18, 10, 0, tzinfo=MADRID)


# --- fakes -------------------------------------------------------------------


class ScriptedSubmitter:
    """A submit client that answers whatever the test asked it to."""

    def __init__(self, status: str, http_status: int | None = 200) -> None:
        self._status = status
        self._http_status = http_status
        self.sent: list[str] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append(action_route(action))
        return SubmitResult(status=self._status, http_status=self._http_status)  # type: ignore[arg-type]

    async def aclose(self) -> None:
        return None


class FakeTask:
    """The end of the pipeline, as far as the watcher can tell."""

    def __init__(self) -> None:
        self.stopped = 0
        self.cancelled = 0

    async def stop_when_done(self) -> None:
        self.stopped += 1

    async def cancel(self) -> None:  # pragma: no cover - must never be called
        self.cancelled += 1


def make_session(settings: Any, call_id: str, submitter: ScriptedSubmitter) -> CallSession:
    start = StartPayload(streamSid=f"MZ-{call_id}", callSid=call_id, customParameters={})
    session = CallSession.open(start, settings=settings, now=NOW)
    session.submitter = submitter  # type: ignore[assignment]
    session.ctx.submitter = submitter  # type: ignore[assignment]
    return session


def a_no_action() -> dict[str, Any]:
    return {"action": NoAction(reason="out_of_scope").model_dump(mode="json")}


def a_rule_that_bit(session: CallSession) -> None:
    """A refusal in the call's memory, as ``check_eligibility`` leaves one."""
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(allowed=False, rejection=Rejection(reason="specialty_not_covered")),
    )


def events(settings: Any, call_id: str, kind: str) -> list[dict[str, Any]]:
    path = Path(settings.calls_log_path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return [x for x in lines if x["call_id"] == call_id and x["kind"] == kind]


# --- the session flag --------------------------------------------------------


async def test_an_accepted_submission_arms_the_hangup(offline_settings) -> None:
    session = make_session(offline_settings, "CA-accepted", ScriptedSubmitter("accepted"))
    assert session.hangup_armed is False

    result = await session.call_tool("submit_action", a_no_action())

    assert result.status == "accepted"
    assert session.hangup_armed is True
    assert session.hangup_reason == "submit_accepted"


async def test_a_duplicate_arms_it_too(offline_settings) -> None:
    """A 409 means the platform already holds that action. Nothing left to do."""
    session = make_session(offline_settings, "CA-duplicate", ScriptedSubmitter("duplicate", 409))

    await session.call_tool("submit_action", a_no_action())

    assert session.hangup_armed is True


@pytest.mark.parametrize("status", ["rejected", "late", "unknown_call", "error", "dry_run"])
async def test_a_submission_the_platform_did_not_take_arms_nothing(
    offline_settings, status: str
) -> None:
    """The model may still fix what it sent, and the fallback is the last word."""
    session = make_session(offline_settings, f"CA-{status}", ScriptedSubmitter(status, 422))

    await session.call_tool("submit_action", a_no_action())

    assert session.hangup_armed is False
    assert session.hangup_reason == ""


async def test_an_accepted_refusal_arms_the_hangup(offline_settings) -> None:
    """The refusal the caller accepted is the ending: there is nothing left to do."""
    session = make_session(offline_settings, "CA-refusal", ScriptedSubmitter("accepted"))
    a_rule_that_bit(session)

    result = await session.submit_accepted_refusal()

    assert result is not None
    assert session.hangup_armed is True
    assert session.hangup_reason == "submit_accepted"


async def test_a_refusal_the_platform_did_not_take_arms_nothing(offline_settings) -> None:
    """Nothing is on record, so the fallback inside the window is still the last word."""
    session = make_session(
        offline_settings, "CA-refusal-rejected", ScriptedSubmitter("rejected", 422)
    )
    a_rule_that_bit(session)

    await session.submit_accepted_refusal()

    assert session.hangup_armed is False


async def test_an_ordinary_tool_call_arms_nothing(offline_settings) -> None:
    session = make_session(offline_settings, "CA-tool", ScriptedSubmitter("accepted"))

    await session.call_tool("resolve_date", {"phrase": "mañana"})

    assert session.hangup_armed is False


async def test_the_end_of_call_fallback_does_not_arm_the_hangup(offline_settings) -> None:
    """``close()`` runs once the socket is already gone: there is nothing to end."""
    session = make_session(offline_settings, "CA-fallback-arm", ScriptedSubmitter("accepted"))

    await session.close()

    assert session.hangup_armed is False


def test_the_first_reason_is_the_one_that_sticks(offline_settings) -> None:
    session = make_session(offline_settings, "CA-first", ScriptedSubmitter("accepted"))

    session.arm_hangup("submit_accepted")
    session.arm_hangup("something_else")

    assert session.hangup_reason == "submit_accepted"


# --- the watcher -------------------------------------------------------------


def watcher(session: CallSession) -> tuple[Any, FakeTask]:
    pytest.importorskip("pipecat")
    from vortex.line.pipecat_voice import _make_hangup_watcher

    guard = _make_hangup_watcher(session)
    task = FakeTask()
    guard.bind(task)
    return guard, task


def pushed(frame: Any) -> Any:
    """What an observer is handed. Only ``frame`` is read."""
    from pipecat.processors.frame_processor import FrameDirection

    return type(
        "FramePushed",
        (),
        {"frame": frame, "direction": FrameDirection.DOWNSTREAM},
    )()


def speaking_frames() -> tuple[Any, Any]:
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame

    return BotStartedSpeakingFrame(), BotStoppedSpeakingFrame()


async def test_an_unarmed_call_is_never_ended(offline_settings) -> None:
    session = make_session(offline_settings, "CA-unarmed", ScriptedSubmitter("rejected"))
    guard, task = watcher(session)
    started, stopped = speaking_frames()

    await guard.on_push_frame(pushed(started))
    await guard.on_push_frame(pushed(stopped))
    await guard.on_user_idle(None)

    assert task.stopped == 0
    assert events(offline_settings, "CA-unarmed", "call.hangup_requested") == []


async def test_the_farewell_ends_the_call(offline_settings) -> None:
    session = make_session(offline_settings, "CA-farewell", ScriptedSubmitter("accepted"))
    await session.call_tool("submit_action", a_no_action())
    guard, task = watcher(session)
    started, stopped = speaking_frames()

    await guard.on_push_frame(pushed(started))
    assert task.stopped == 0  # still talking
    await guard.on_push_frame(pushed(stopped))

    assert task.stopped == 1
    (event,) = events(offline_settings, "CA-farewell", "call.hangup_requested")
    assert event["reason"] == "farewell_spoken"
    assert event["armed_by"] == "submit_accepted"
    # The transport pushes both frames twice, up and down. Once is enough.
    await guard.on_push_frame(pushed(started))
    await guard.on_push_frame(pushed(stopped))
    assert task.stopped == 1
    assert task.cancelled == 0


async def test_the_sentence_that_was_already_playing_does_not_count(offline_settings) -> None:
    """The model often speaks before its tool call, and that audio lags.

    Ending on *that* utterance would cut the goodbye it has not said yet, so
    only an utterance that started after the platform answered counts.
    """
    session = make_session(offline_settings, "CA-midword", ScriptedSubmitter("accepted"))
    started, stopped = speaking_frames()
    guard, task = watcher(session)

    # Speaking already, then the submission lands, then that utterance ends.
    await guard.on_push_frame(pushed(started))
    await session.call_tool("submit_action", a_no_action())
    await guard.on_push_frame(pushed(stopped))
    assert task.stopped == 0

    # The goodbye. This one started after the submission, so it is the one.
    await guard.on_push_frame(pushed(started))
    await guard.on_push_frame(pushed(stopped))
    assert task.stopped == 1


async def test_a_silent_caller_after_a_submission_ends_the_call(offline_settings) -> None:
    """The model submitted and then said nothing. Do not hold the line to the cap."""
    session = make_session(offline_settings, "CA-idle", ScriptedSubmitter("accepted"))
    await session.call_tool("submit_action", a_no_action())
    guard, task = watcher(session)

    await guard.on_user_idle(None)

    assert task.stopped == 1
    (event,) = events(offline_settings, "CA-idle", "call.hangup_requested")
    assert event["reason"] == "idle_after_submit"


async def test_the_watcher_without_a_task_never_raises(offline_settings) -> None:
    """Observers are built before the task exists; a frame in between is a no-op."""
    pytest.importorskip("pipecat")
    from vortex.line.pipecat_voice import _make_hangup_watcher

    session = make_session(offline_settings, "CA-unbound", ScriptedSubmitter("accepted"))
    await session.call_tool("submit_action", a_no_action())
    guard = _make_hangup_watcher(session)
    started, stopped = speaking_frames()

    await guard.on_push_frame(pushed(started))
    await guard.on_push_frame(pushed(stopped))

    assert events(offline_settings, "CA-unbound", "call.hangup_requested") == []


def test_the_end_is_graceful_not_a_cancel() -> None:
    """``stop_when_done`` drains what is in flight; ``cancel`` cuts it off.

    The farewell audio is still on its way out when the end frame is queued, so
    the difference is whether the caller hears the goodbye.
    """
    pytest.importorskip("pipecat")
    import inspect

    from vortex.line import pipecat_voice

    source = inspect.getsource(pipecat_voice._make_hangup_watcher)
    assert "stop_when_done" in source
    assert "task.cancel(" not in source


def test_the_watcher_is_wired_into_the_pipeline() -> None:
    """Both halves of it, or the call still runs to the three-minute cap.

    The watcher only ends the call if it sees the frames (as an observer) and
    the silences (as a handler on the user aggregator), and it can only end
    anything once it holds the task. Read off the source because building the
    real pipeline needs the four provider keys.
    """
    pytest.importorskip("pipecat")
    import inspect

    from vortex.line.pipecat_voice import run_pipecat_call

    source = inspect.getsource(run_pipecat_call)
    assert "hangup = _make_hangup_watcher(session)" in source
    assert "observers=[_CallLogObserver(session, filler_guard=filler_guard), hangup]" in source
    assert "hangup.bind(task)" in source
    assert '"on_user_turn_idle", hangup.on_user_idle' in source
