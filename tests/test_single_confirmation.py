"""One confirmation: the caller's first yes books the appointment.

The failure this closes, from the 2026-09-19 board notes: the agent read the
plan back, the caller said "yes, book it", and the agent read the same plan back
again. The second question ate the wall clock and some of those calls ended with
no submission at all - a lost case with a perfect conversation in front of it.

Two halves, both tested here and neither needing a model:

- ``ConfirmationPolicy`` decides, from the transcript alone, that a caller turn
  is an agreement to a read-back.
- ``CallSession.confirm_prepared`` sends what is already drawn up, so the
  submission does not wait on the model asking again.

The prompt carries the same rule for the model itself, which is the last
assertion in the file. Everything runs offline: the submit client is a fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from vortex.contract import (
    MADRID,
    Action,
    BookAction,
    BookingResult,
    Rejection,
    Slot,
    SubmitResult,
    action_payload,
    action_route,
)
from vortex.conversation.prompt import build_system_prompt
from vortex.conversation.turns import (
    ConfirmationPolicy,
    is_affirmation,
    looks_like_confirmation_question,
)
from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload

NOW = datetime(2026, 9, 18, 10, 0, tzinfo=MADRID)  # a Friday
SLOT = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)
PATIENT = "P00042"

READ_BACK = "Tuesday the 24th at half past four with Doctor Cid, at Sur. Shall I book it?"


class AcceptingSubmitter:
    """A submit client the platform always answers 200 to."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="accepted", http_status=200)

    async def aclose(self) -> None:
        return None


def make_session(settings, call_id: str) -> CallSession:
    start = StartPayload(streamSid=f"MZ-{call_id}", callSid=call_id, customParameters={})
    session = CallSession.open(start, settings=settings, now=NOW)
    session.submitter = AcceptingSubmitter()
    session.ctx.submitter = session.submitter
    return session


def sent(session: CallSession) -> list[tuple[str, dict[str, Any]]]:
    return list(session.submitter.sent)


def a_booking() -> BookAction:
    return BookAction(
        patient_id=PATIENT,
        provider_id="PR05",
        location_id="sur",
        appointment_type_id="review",
        slot=SLOT,
        policy_id="sanitas",
    )


async def an_offered_slot(session: CallSession) -> Slot:
    """A slot the fake clinic is really offering: prepare_booking rejects any other."""
    day = (NOW + timedelta(days=1)).date()
    answer = await session.ctx.clinic.availability(
        date_from=day, date_to=day, specialty_id="general_practice", patient_id=PATIENT
    )
    assert answer.slots, f"fake clinic offers nothing on {day}"
    return answer.slots[0]


# ---- what counts as a yes ----------------------------------------------------


@pytest.mark.parametrize(
    "said",
    [
        "yes",
        "Yes, book it.",
        "yeah that works",
        "ok",
        "perfect",
        "go ahead",
        "sí",
        "si, perfecto",
        "vale",
        "dale",
        "de acuerdo",
        "d'acord",
        "bai",
    ],
)
def test_a_plain_yes_is_an_affirmation(said: str) -> None:
    assert is_affirmation(said)


@pytest.mark.parametrize(
    "said",
    [
        "no",
        "no, not that one",
        "yes, but make it Friday instead",
        "yes, actually can we change the doctor",
        "hmm",
        "sorry, could you repeat that",
        "mejor el viernes",
        "sí, pero espera",
        "",
    ],
)
def test_anything_that_takes_it_back_is_not_an_affirmation(said: str) -> None:
    assert not is_affirmation(said)


def test_a_read_back_is_a_question_about_the_appointment() -> None:
    assert looks_like_confirmation_question(READ_BACK)
    assert looks_like_confirmation_question("¿Le confirmo la cita del martes?")
    assert not looks_like_confirmation_question("Could you tell me your date of birth?")
    assert looks_like_confirmation_question("Half past four, then?", prepared=True)
    assert not looks_like_confirmation_question("I have booked that for you.")


# ---- the policy over a transcript -------------------------------------------


def test_a_yes_to_a_read_back_confirms() -> None:
    policy = ConfirmationPolicy()
    policy.on_assistant_text(READ_BACK)

    decision = policy.on_user_text("yes, book it")

    assert decision.confirmed
    assert "book it" in decision.why


def test_the_agents_turn_is_reassembled_from_tts_fragments() -> None:
    """TTS text arrives a few words at a time; the question mark is its own frame."""
    policy = ConfirmationPolicy()
    for fragment in ("Tuesday at half past four", "with Doctor Cid.", "Shall I book it", "?"):
        policy.on_assistant_text(fragment)

    assert policy.on_user_text("dale").confirmed


def test_a_yes_out_of_the_blue_confirms_nothing() -> None:
    policy = ConfirmationPolicy()
    policy.on_assistant_text("What is your date of birth?")

    assert not policy.on_user_text("yes").confirmed


def test_a_split_transcript_still_finds_the_yes() -> None:
    """The caller's turn can reach us as two transcripts. The question survives."""
    policy = ConfirmationPolicy()
    policy.on_assistant_text(READ_BACK)

    assert not policy.on_user_text("well").confirmed
    assert policy.on_user_text("yes, that's right").confirmed


def test_the_agent_speaking_again_replaces_the_question() -> None:
    policy = ConfirmationPolicy()
    policy.on_assistant_text(READ_BACK)
    policy.on_user_text("hold on")
    policy.on_assistant_text("Of course. Which day suits you?")

    assert not policy.on_user_text("yes").confirmed


def test_two_calls_never_share_a_confirmation() -> None:
    first, second = ConfirmationPolicy(), ConfirmationPolicy()
    first.on_assistant_text(READ_BACK)

    assert not second.on_user_text("yes").confirmed


# ---- the session: the yes submits -------------------------------------------


async def test_the_yes_submits_what_is_already_prepared(offline_settings) -> None:
    session = make_session(offline_settings, "CA-yes-after-prepare")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))

    session.confirm_prepared("caller affirmed: yes, book it")
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/book"
    assert payload["slot"].startswith("2026-09-24T16:30")
    assert len(sent(session)) == 1, "the fallback must not send it a second time"
    assert session.has_accepted_submission


async def test_a_prepare_after_the_yes_needs_no_second_question(offline_settings) -> None:
    """The model usually draws the booking up after the caller has agreed to it."""
    session = make_session(offline_settings, "CA-prepare-after-yes")
    session.confirm_prepared("caller affirmed: dale")
    assert sent(session) == []

    slot = await an_offered_slot(session)
    result = await session.call_tool(
        "prepare_booking",
        {"patient_id": PATIENT, "slot": slot.model_dump(mode="json"), "policy_id": "sanitas"},
    )

    assert result.rejection is None
    assert [route for route, _ in sent(session)] == ["/api/v1/submit/book"]


async def test_nothing_is_submitted_without_the_yes(offline_settings) -> None:
    session = make_session(offline_settings, "CA-no-yes")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))

    assert await session.submit_confirmed_prepared("affirmation") is None
    assert sent(session) == []


async def test_a_rule_that_bit_leaves_nothing_to_agree_to(offline_settings) -> None:
    """A rejection drops the prepared action, so a yes cannot send one."""
    session = make_session(offline_settings, "CA-yes-then-rule")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    session.memory.observe(
        "prepare_booking", BookingResult(rejection=Rejection(reason="allowance_exhausted"))
    )

    session.confirm_prepared("caller affirmed: yes")

    assert sent(session) == []
    assert session.memory.prepared is None


async def test_the_same_action_never_goes_twice(offline_settings) -> None:
    session = make_session(offline_settings, "CA-once")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    session.memory.mark_confirmed()

    assert await session.submit_confirmed_prepared("affirmation") is not None
    assert await session.submit_confirmed_prepared("affirmation") is None
    assert len(sent(session)) == 1


# ---- the model is told the same thing ---------------------------------------


def test_the_prompt_tells_the_model_not_to_ask_twice() -> None:
    text = build_system_prompt(NOW)
    assert "Never ask twice" in text
    assert "Do not submit before the caller agrees" in text
