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
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from vortex.contract import (
    FAKE_PATIENT,
    MADRID,
    Action,
    AvailabilityResult,
    BlockedProvider,
    BookAction,
    BookingResult,
    CallerLineMatch,
    EligibilityVerdict,
    FindPatientResult,
    NoAction,
    RegisterAction,
    RegistrationResult,
    Rejection,
    RescheduleResult,
    Slot,
    SubmitResult,
    TriageResult,
    action_payload,
    action_route,
)
from vortex.identity.tools import PATIENT_PREFERENCES_KEY
from vortex.line.session import CallMemory, CallSession
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


def make_session(settings, call_id: str = "CA-fallback", clinic: Any = None) -> CallSession:
    start = StartPayload(streamSid=f"MZ-{call_id}", callSid=call_id, customParameters={})
    return CallSession.open(start, settings=settings, clinic=clinic, now=NOW)


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


def a_registration() -> RegisterAction:
    return RegisterAction(
        given_name="Amelia",
        first_surname="Hughes",
        second_surname="Ferrer",
        national_id="12345678Z",
        date_of_birth=date(1990, 4, 2),
        phone="+34600111222",
        email="amelia@example.com",
        insurer="mapfre",
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


async def test_the_fallback_names_the_verdict_not_the_last_tool(offline_settings) -> None:
    """A rule the call already holds outranks the wording of whoever spoke last."""
    session = make_session(offline_settings, "CA-verdict-wins")
    session.ctx.log.user_turn("fisioterapia con ASISA en la sede sur")
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(
            allowed=False,
            rejection=Rejection(reason="location_not_covered", detail="ASISA, sede sur"),
        ),
    )
    session.memory.observe(
        "prepare_booking", BookingResult(rejection=Rejection(reason="no_availability"))
    )
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "location_not_covered"
    assert [action.reason for action in session.sent_actions] == ["location_not_covered"]
    (event,) = events(offline_settings, "CA-verdict-wins", "submit.fallback")
    assert event["branch"] == "last_rejection"
    assert event["retrying"] is False


# --- branch (c): a reason a later plan would have dropped -----------------------


async def test_an_unconfirmed_plan_does_not_downgrade_a_named_reason(
    offline_settings,
) -> None:
    """The rule that bit outlives the alternative nobody agreed to."""
    session = make_session(offline_settings, "CA-kept-reason")
    session.ctx.log.user_turn("con la doctora Cid, tengo ASISA")
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(
            allowed=False,
            rejection=Rejection(reason="location_not_covered", detail="ASISA, sede sur"),
        ),
    )
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    await session.close()

    assert session.memory.last_rejection is None
    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "location_not_covered"
    event = events(offline_settings, "CA-kept-reason", "submit.fallback")[0]
    assert event["branch"] == "stored_reason"
    assert "check_eligibility" in event["why"]


async def test_a_red_flag_survives_an_unconfirmed_plan(offline_settings) -> None:
    session = make_session(offline_settings, "CA-kept-flag")
    session.ctx.log.user_turn("me duele el pecho")
    session.memory.observe(
        "triage", TriageResult(emergency=True, rejection=Rejection(reason="medical_emergency"))
    )
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    await session.close()

    assert sent(session)[0][0] == "/api/v1/submit/escalate"
    assert sent(session)[0][1]["reason"] == "medical_emergency"


async def test_a_confirmed_plan_still_wins_over_a_stored_reason(offline_settings) -> None:
    """The caller's yes is the one thing that outranks a named refusal."""
    session = make_session(offline_settings, "CA-kept-book")
    session.ctx.log.user_turn("si, con el otro medico entonces")
    session.memory.observe(
        "find_slots", AvailabilityResult(rejection=Rejection(reason="provider_on_leave"))
    )
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    session.ctx.memory.mark_confirmed()
    await session.close()

    assert sent(session)[0][0] == "/api/v1/submit/book"


async def test_free_slots_drop_an_earlier_rejection(offline_settings) -> None:
    session = make_session(offline_settings, "CA-cleared")
    session.ctx.log.user_turn("el martes")
    session.memory.observe(
        "find_slots", AvailabilityResult(rejection=Rejection(reason="no_availability"))
    )
    session.memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    await session.close()

    assert session.memory.last_rejection is None
    assert session.memory.stored_reason is None
    assert sent(session)[0][1]["reason"] == "out_of_scope"


# --- branch (a): an action prepared and never sent ----------------------------


async def test_an_unconfirmed_prepared_action_is_still_sent(offline_settings) -> None:
    """A plan nobody got to agree to beats a refusal no case accepts."""
    session = make_session(offline_settings, "CA-unconfirmed")
    session.ctx.log.user_turn("el jueves por la tarde")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/book"
    assert payload["patient_id"] == "P00042"
    assert payload["slot"].startswith("2026-09-24T16:30")
    event = events(offline_settings, "CA-unconfirmed", "submit.fallback")[0]
    assert event["branch"] == "prepared_unconfirmed"


async def test_an_unconfirmed_registration_is_still_sent(offline_settings) -> None:
    """the_new_patient ends on REGISTER, and those calls die at the wall clock."""
    session = make_session(offline_settings, "CA-unconfirmed-register")
    session.ctx.log.user_turn("no soy paciente, me quiero dar de alta")
    session.memory.observe("build_registration", RegistrationResult(action=a_registration()))
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/register"
    assert payload["national_id"] == "12345678Z"
    assert (
        events(offline_settings, "CA-unconfirmed-register", "submit.fallback")[0]["branch"]
        == "prepared_unconfirmed"
    )


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


# --- branch (e): both halves of a booking, drawn up by nobody -----------------


async def test_a_patient_and_a_free_slot_are_booked(offline_settings) -> None:
    """The wall clock cut the call between the search and the read-back."""
    session = make_session(offline_settings, "CA-draft")
    session.ctx.log.user_turn("el jueves a las cuatro y media")
    session.memory.observe("find_patient", FindPatientResult(status="found", patient=FAKE_PATIENT))
    session.memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/book"
    assert payload["patient_id"] == FAKE_PATIENT.patient_id
    assert payload["provider_id"] == "PR05"
    assert payload["location_id"] == "sur"
    assert payload["appointment_type_id"] == "review"
    assert payload["policy_id"] == FAKE_PATIENT.insurer
    assert payload["slot"].startswith("2026-09-24T16:30")
    assert events(offline_settings, "CA-draft", "submit.fallback")[0]["branch"] == "draft_booking"


async def test_the_draft_books_the_latest_search(offline_settings) -> None:
    """The caller narrowed the window; the last search is the one being read back."""
    session = make_session(offline_settings, "CA-draft-latest")
    session.ctx.log.user_turn("mejor por la manana")
    session.memory.observe("find_patient", FindPatientResult(status="found", patient=FAKE_PATIENT))
    session.memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    later = a_slot().model_copy(update={"start": SLOT.replace(hour=9, minute=15)})
    session.memory.observe("find_slots", AvailabilityResult(slots=[later]))
    await session.close()

    assert sent(session)[0][1]["slot"].startswith("2026-09-24T09:15")


async def test_the_draft_bills_the_slot_when_the_record_names_no_plan(offline_settings) -> None:
    session = make_session(offline_settings, "CA-draft-policy")
    session.ctx.log.user_turn("pues ese mismo")
    uninsured = FAKE_PATIENT.model_copy(update={"insurer": ""})
    session.memory.observe("find_patient", FindPatientResult(status="found", patient=uninsured))
    session.memory.observe(
        "find_slots",
        AvailabilityResult(slots=[a_slot().model_copy(update={"payable_with": ["adeslas"]})]),
    )
    await session.close()

    assert sent(session)[0][1]["policy_id"] == "adeslas"


async def test_the_draft_falls_back_to_self_pay(offline_settings) -> None:
    session = make_session(offline_settings, "CA-draft-self-pay")
    session.ctx.log.user_turn("no tengo seguro")
    uninsured = FAKE_PATIENT.model_copy(update={"insurer": ""})
    session.memory.observe("find_patient", FindPatientResult(status="found", patient=uninsured))
    session.memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    await session.close()

    assert sent(session)[0][1]["policy_id"] == "privado"


def test_no_draft_without_both_halves() -> None:
    """A booking is only ever drafted off ids the API gave us."""
    memory = CallMemory()
    assert memory.draft_booking() is None

    memory.observe("find_patient", FindPatientResult(status="found", patient=FAKE_PATIENT))
    assert memory.draft_booking() is None

    memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    assert memory.draft_booking() is not None


def test_no_draft_while_the_lookup_is_still_open() -> None:
    """Two namesakes and no second field: we do not know whose slot this is."""
    memory = CallMemory()
    memory.observe("find_patient", FindPatientResult(status="found", patient=FAKE_PATIENT))
    memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    memory.observe("find_patient", FindPatientResult(status="ambiguous", ask_for="date_of_birth"))

    assert memory.draft_booking() is None


async def test_a_named_rule_outranks_a_drafted_booking(offline_settings) -> None:
    session = make_session(offline_settings, "CA-draft-vs-rule")
    session.ctx.log.user_turn("con la doctora Cid")
    session.memory.observe("find_patient", FindPatientResult(status="found", patient=FAKE_PATIENT))
    session.memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(allowed=False, rejection=Rejection(reason="referral_required")),
    )
    await session.close()

    assert sent(session)[0][1]["reason"] == "referral_required"


# --- branch (g): the line died with the lookup still open ----------------------


async def test_an_unfinished_lookup_ends_on_patient_not_found(offline_settings) -> None:
    """The caller gave a name, the line dropped: we never learned whose call it was."""
    session = make_session(offline_settings, "CA-mid-identity")
    session.ctx.log.user_turn("soy Amelia Hughes, quiero cita con el medico de cabecera")
    session.memory.observe(
        "find_patient", FindPatientResult(status="ambiguous", ask_for="date_of_birth")
    )
    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "patient_not_found"
    event = events(offline_settings, "CA-mid-identity", "submit.fallback")[0]
    assert event["branch"] == "identity_pending"


async def test_an_identified_patient_clears_the_unfinished_lookup(offline_settings) -> None:
    """A later match ends ``patient_not_found``: the call knows whose it is."""
    session = make_session(offline_settings, "CA-identified")
    session.ctx.log.user_turn("mi fecha de nacimiento es 12 de marzo del 85")
    session.memory.observe("find_patient", FindPatientResult(status="not_found"))
    session.memory.observe("find_patient", FindPatientResult(status="found", patient=FAKE_PATIENT))
    await session.close()

    assert session.memory.identity_pending is False
    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/book"
    assert payload["patient_id"] == FAKE_PATIENT.patient_id


async def test_a_named_rule_outranks_an_unfinished_lookup(offline_settings) -> None:
    session = make_session(offline_settings, "CA-rule-over-identity")
    session.ctx.log.user_turn("quiero cita de fisioterapia")
    session.memory.observe("find_patient", FindPatientResult(status="not_found"))
    session.memory.observe(
        "check_eligibility",
        EligibilityVerdict(allowed=False, rejection=Rejection(reason="specialty_not_covered")),
    )
    await session.close()

    assert sent(session)[0][1]["reason"] == "specialty_not_covered"


# --- the cold booking: out_of_scope is a certain zero -------------------------


class BrokenCatalogue:
    """A clinic that is down. The refusal the fallback already had must go out."""

    async def catalogue(self) -> Any:
        raise RuntimeError("the clinic is down")


class SlowCatalogue:
    """A clinic that never answers, so the timeout is the thing under test."""

    async def catalogue(self) -> Any:
        await asyncio.sleep(30)
        raise AssertionError("unreachable")


def line_owner(session: CallSession, patient: Any = FAKE_PATIENT) -> None:
    """What the caller-id lookup leaves behind on a call that resolves nothing."""
    session.memory.caller_line = CallerLineMatch(
        looked_up=True, from_number=patient.phone, patient=patient, candidates=[patient]
    )


def habit(session: CallSession, patient_id: str, provider_id: str, location_id: str = "") -> None:
    """What the identity lane mines off a patient's visit history in the background."""
    session.ctx.state[PATIENT_PREFERENCES_KEY] = {
        "patient_id": patient_id,
        "provider_preference": provider_id,
        "location_preference": location_id,
    }


async def test_a_silent_call_books_the_doctor_the_line_always_uses(offline_settings) -> None:
    """Nobody said a word, and the call still ends on the booking it can defend.

    The caller-id lookup named the line's owner before the greeting and mined
    the one doctor every past visit of theirs used. ``out_of_scope`` wins no
    published case, so that habit is worth more than the refusal.
    """
    session = make_session(offline_settings, "CA-cold-habit")
    line_owner(session)
    habit(session, FAKE_PATIENT.patient_id, "PR02")

    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/book"
    assert payload["patient_id"] == "P00042"
    assert payload["provider_id"] == "PR02"
    assert payload["location_id"] == "norte"
    assert payload["policy_id"] == "sanitas"
    assert payload["slot"] > NOW.isoformat()
    (fallback,) = events(offline_settings, "CA-cold-habit", "submit.fallback")
    assert fallback["branch"] == "cold_booking"
    (booking,) = events(offline_settings, "CA-cold-habit", "submit.cold_booking")
    assert booking["from_line"] is True


async def test_the_appointment_type_comes_off_the_slot(offline_settings) -> None:
    """Never a type we chose: the platform compares the slot's own id exactly."""
    session = make_session(offline_settings, "CA-cold-type")
    line_owner(session)
    habit(session, FAKE_PATIENT.patient_id, "PR04")

    await session.close()

    assert sent(session)[0][1]["appointment_type_id"] == "dermatology_review"


async def test_without_a_habit_the_cold_booking_asks_for_general_practice(
    offline_settings,
) -> None:
    """``/availability`` answers no query naming neither provider nor specialty."""
    session = make_session(offline_settings, "CA-cold-gp")
    line_owner(session)

    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/book"
    assert payload["provider_id"] == "PR01"
    assert payload["location_id"] == "centro"


async def test_a_habit_mined_for_somebody_else_is_not_used(offline_settings) -> None:
    """The line owner's doctor is not the doctor of whoever the call identified."""
    session = make_session(offline_settings, "CA-cold-other")
    line_owner(session)
    habit(session, "P00107", "PR02")

    await session.close()

    assert session._habits_of(FAKE_PATIENT) == (None, None)
    assert sent(session)[0][1]["provider_id"] == "PR01"


async def test_a_named_reason_is_never_traded_for_a_cold_booking(offline_settings) -> None:
    """The rule that bit outranks the guess. This is what F1 and F3 established."""
    session = make_session(offline_settings, "CA-cold-vs-rule")
    line_owner(session)
    habit(session, FAKE_PATIENT.patient_id, "PR02")
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
    assert events(offline_settings, "CA-cold-vs-rule", "submit.cold_booking") == []


async def test_an_explicit_out_of_scope_rejection_is_never_traded_for_a_cold_booking(
    offline_settings,
) -> None:
    """The cold booking replaces the ``out_of_scope`` nobody named, not the one a tool did.

    ``out_of_scope`` is the ending problem 14 is accepted on, and the reason a
    tool returns is the reason we submit. Only the branches that reach it having
    named no rule at all are worth trading for the guess off the line.
    """
    session = make_session(offline_settings, "CA-cold-vs-scope")
    line_owner(session)
    habit(session, FAKE_PATIENT.patient_id, "PR02")
    session.ctx.log.user_turn("quiero mover la cita de mi vecina")
    session.memory.observe(
        "prepare_reschedule",
        RescheduleResult(
            rejection=Rejection(
                reason="out_of_scope",
                detail="appointment AP99 is in no diary this call has read",
            )
        ),
    )

    await session.close()

    route, payload = sent(session)[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "out_of_scope"
    assert events(offline_settings, "CA-cold-vs-scope", "submit.cold_booking") == []


async def test_a_prepared_action_is_never_traded_for_a_cold_booking(offline_settings) -> None:
    """A plan a tool drew up is the call's own answer, not a guess off the line."""
    session = make_session(offline_settings, "CA-cold-vs-prepared")
    line_owner(session)
    habit(session, FAKE_PATIENT.patient_id, "PR02")
    session.memory.observe("prepare_booking", BookingResult(action=a_booking()))

    await session.close()

    assert sent(session)[0][1]["provider_id"] == "PR05"
    assert events(offline_settings, "CA-cold-vs-prepared", "submit.cold_booking") == []


async def test_a_line_on_no_record_still_ends_on_out_of_scope(offline_settings) -> None:
    """No patient, no booking to guess at. The refusal is all there is."""
    session = make_session(offline_settings, "CA-cold-nobody")
    session.memory.caller_line = CallerLineMatch(looked_up=True, from_number="+34600000000")

    await session.close()

    assert sent(session)[0][1]["reason"] == "out_of_scope"
    assert events(offline_settings, "CA-cold-nobody", "submit.cold_booking") == []


async def test_a_clinic_that_is_down_leaves_the_refusal_alone(offline_settings) -> None:
    session = make_session(offline_settings, "CA-cold-broken", clinic=BrokenCatalogue())
    line_owner(session)

    await session.close()

    assert sent(session)[0][1]["reason"] == "out_of_scope"
    (failure,) = events(offline_settings, "CA-cold-broken", "submit.cold_booking_failed")
    assert "RuntimeError" in failure["detail"]


async def test_the_cold_booking_gives_up_inside_the_submit_window(offline_settings) -> None:
    """A booking that misses the window is worth less than a refusal that makes it."""
    settings = dataclasses.replace(offline_settings, cold_booking_timeout_secs=0.05)
    session = make_session(settings, "CA-cold-slow", clinic=SlowCatalogue())
    line_owner(session)

    started = time.monotonic()
    await session.close()

    assert time.monotonic() - started < settings.submit_window_secs
    assert sent(session)[0][1]["reason"] == "out_of_scope"
    assert events(settings, "CA-cold-slow", "submit.cold_booking_timed_out")


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
