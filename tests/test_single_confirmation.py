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

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest

from vortex.contract import (
    MADRID,
    Action,
    AvailabilityResult,
    BookAction,
    BookingResult,
    EligibilityVerdict,
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
    is_refusal_acceptance,
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


class GatedSubmitter(AcceptingSubmitter):
    """The same client, with the POST held open until the test lets it answer.

    A real POST is in flight for as long as the platform takes to answer, and
    that is the window the next caller turn arrives in.
    """

    def __init__(self) -> None:
        super().__init__()
        self.in_flight = asyncio.Event()
        self.answer = asyncio.Event()

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.in_flight.set()
        await self.answer.wait()
        return await super().submit(call_id, action)


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
        "yes please",
        "ok, thank you",
        "sí, por favor",
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


@pytest.mark.parametrize(
    "said",
    [
        "yes, Friday please",
        "yes, at five",
        "ok, with Doctor Cid",
        "sure, in Norte",
        "vale, a las cinco",
        "sí, el jueves",
    ],
)
def test_a_yes_that_names_something_new_is_not_an_affirmation(said: str) -> None:
    """A yes carrying a detail we never read back is a request, not agreement."""
    assert not is_affirmation(said)


@pytest.mark.parametrize(
    "said",
    [
        "Ah, I see.",
        "I understand",
        "Okay, I understand.",
        "thanks anyway",
        "ya veo",
        "lo entiendo",
        "entendido",
    ],
)
def test_accepting_the_refusal_is_not_a_yes_to_another_policy(said: str) -> None:
    assert is_refusal_acceptance(said)
    assert not is_affirmation(said)


@pytest.mark.parametrize(
    "said",
    [
        "yes",
        "sí",
        "vale",
        "I do have a referral",
        "why doesn't it cover it",
        "I have another policy",
        "",
    ],
)
def test_a_yes_or_a_challenge_is_not_accepting_the_refusal(said: str) -> None:
    assert not is_refusal_acceptance(said)


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


async def test_accepting_the_refusal_submits_it_at_once(offline_settings) -> None:
    """Call 6d537b3a: they said 'Ah, I see' and we asked about another policy."""
    session = make_session(offline_settings, "CA-ah-i-see")
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(
            allowed=False,
            rejection=Rejection(reason="specialty_not_covered"),
        ),
    )

    session.accept_refusal("caller accepted the refusal: Ah, I see.")
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "specialty_not_covered"
    assert len(sent(session)) == 1


async def test_a_second_acceptance_never_sends_the_refusal_twice(offline_settings) -> None:
    """Two acceptance turns in a row, with the platform answering after both."""
    session = make_session(offline_settings, "CA-ah-i-see-twice")
    submitter = GatedSubmitter()
    session.submitter = submitter
    session.ctx.submitter = submitter
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(
            allowed=False,
            rejection=Rejection(reason="specialty_not_covered"),
        ),
    )

    session.accept_refusal("caller accepted the refusal: Ah, I see.")
    await submitter.in_flight.wait()
    session.accept_refusal("caller accepted the refusal: Right, thanks.")
    await asyncio.sleep(0)  # let the second task reach the POST it must not make
    submitter.answer.set()
    await session.close()

    assert [route for route, _ in sent(session)] == ["/api/v1/submit/no-action"]


async def test_a_yes_to_another_policy_does_not_submit_the_refusal(offline_settings) -> None:
    session = make_session(offline_settings, "CA-other-policy")
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(
            allowed=False,
            rejection=Rejection(reason="specialty_not_covered"),
        ),
    )
    session.confirm_prepared("caller affirmed: yes")

    assert sent(session) == []
    assert session.memory.last_rejection is not None


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
    assert "If they accept the refusal" in text


# ---- the yes belongs to the offer on the table ------------------------------
#
# Run 540d5092, call 8c8a7c54, 0 of 2 points. The agent offered Centro on the
# 21st and drew it up. The caller then said "I need it at Arenal Norte, please,
# not Centro"; the agent searched Norte, offered the 22nd, and asked. On "Sure"
# the first yes spent itself on the Centro plan still sitting in memory, so the
# call submitted Centro *and*, once the model drew Norte up properly, Norte too.
# Two bookings is a mismatched record.


def another_slot(start: datetime) -> Slot:
    return Slot(
        start=start,
        provider_id="PR07",
        location_id="norte",
        appointment_type_id="review",
    )


def a_search(*starts: datetime) -> AvailabilityResult:
    return AvailabilityResult(slots=[another_slot(start) for start in starts])


ELSEWHERE = datetime(2026, 9, 25, 9, 0, tzinfo=MADRID)


async def test_a_search_past_the_prepared_slot_drops_the_plan(offline_settings) -> None:
    """The caller moved off it, so no yes can send it."""
    session = make_session(offline_settings, "CA-superseded")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))

    session.memory.observe("find_slots", a_search(ELSEWHERE))

    assert session.memory.prepared is None


async def test_the_yes_after_that_search_submits_nothing(offline_settings) -> None:
    """The failure itself: one yes, and it must not book what was turned down."""
    session = make_session(offline_settings, "CA-superseded-yes")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    session.memory.observe("find_slots", a_search(ELSEWHERE))

    session.confirm_prepared("caller affirmed: Sure.")
    await session.close()

    booked = [payload.get("slot", "") for _, payload in sent(session)]
    assert not any(slot.startswith("2026-09-24T16:30") for slot in booked), (
        f"booked the slot the caller turned down: {booked}"
    )


async def test_that_yes_still_counts_for_the_offer_it_was_given_to(offline_settings) -> None:
    """Dropping the plan must not cost the caller a second question: the next
    booking the model draws up goes out on the yes they already gave."""
    session = make_session(offline_settings, "CA-superseded-then-prepared")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    session.memory.observe("find_slots", a_search(ELSEWHERE))
    session.confirm_prepared("caller affirmed: Sure.")

    slot = await an_offered_slot(session)
    result = await session.call_tool(
        "prepare_booking",
        {"patient_id": PATIENT, "slot": slot.model_dump(mode="json"), "policy_id": "sanitas"},
    )

    assert result.rejection is None
    routes = [route for route, _ in sent(session)]
    assert routes == ["/api/v1/submit/book"], "exactly one booking, and it is the new one"
    assert sent(session)[0][1]["slot"].startswith(slot.start.isoformat()[:16])


async def test_a_search_that_still_offers_the_slot_keeps_the_plan(offline_settings) -> None:
    """The regression guard. Re-reading the same availability is not a change of
    mind, and every ordinary booking call searches before it prepares."""
    session = make_session(offline_settings, "CA-same-slot")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))

    session.memory.observe("find_slots", a_search(ELSEWHERE, SLOT))

    assert session.memory.prepared is not None
    session.confirm_prepared("caller affirmed: yes")
    await session.close()
    assert [payload["slot"] for _, payload in sent(session)][0].startswith("2026-09-24T16:30")


async def test_an_empty_search_leaves_the_plan_alone(offline_settings) -> None:
    """No availability is not another offer. It must not silently drop a booking."""
    session = make_session(offline_settings, "CA-no-slots")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))

    session.memory.observe("find_slots", AvailabilityResult(slots=[]))

    assert session.memory.prepared is not None


async def test_a_search_before_anything_is_prepared_is_harmless(offline_settings) -> None:
    session = make_session(offline_settings, "CA-search-first")

    session.memory.observe("find_slots", a_search(ELSEWHERE))

    assert session.memory.prepared is None
    assert session.memory.free_slot is not None
