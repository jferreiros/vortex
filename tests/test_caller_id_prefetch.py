"""The caller-id prefetch: who the line belongs to, before the caller speaks.

Twilio hands us the dialling number on the ``start`` message and ``/directory``
accepts a phone on its own, so the whole opening exchange - the name, then a
second identifier, one field per turn - is answerable for free before the
greeting. The scored run of 2026-09-19 lost five cases (11 of 40 points) to
calls that never reached a single tool: three of them had already said a name
the directory would have matched, and two were new patients who spent ninety
seconds dictating a phone number the caller id had carried all along.

Everything here runs offline against the fixture directory. No sockets, no keys.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import date, datetime
from typing import Any

import pytest

from vortex.contract import (
    FAKE_PATIENT,
    MADRID,
    AvailabilityResult,
    CallerLineMatch,
    FindPatientResult,
    PatientRecord,
    Slot,
    ToolContext,
)
from vortex.conversation.prompt import build_system_prompt, caller_note_for, initial_messages
from vortex.identity.tools import CALLER_IDENTITY_KEY, resolve_caller_line
from vortex.line.session import CallMemory, CallSession
from vortex.line.twilio import StartPayload
from vortex.observability.calllog import CallLog

NOW = datetime(2026, 9, 18, 10, 0, tzinfo=MADRID)
SLOT = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)

pytestmark = pytest.mark.anyio


# --- fakes -------------------------------------------------------------------


class DirectoryStub:
    """A clinic whose ``/directory`` answers a fixed list, and records the query."""

    def __init__(self, matches: list[PatientRecord] | None = None) -> None:
        self.matches = matches or []
        self.queries: list[dict[str, Any]] = []

    async def directory(self, **kwargs: Any) -> list[PatientRecord]:
        self.queries.append(kwargs)
        return list(self.matches)


class BrokenDirectory:
    """A clinic that is down. The call must carry on without the note."""

    async def directory(self, **kwargs: Any) -> list[PatientRecord]:
        raise RuntimeError("directory is down")


class SlowDirectory:
    """A clinic that never answers, so the timeout is the thing under test."""

    async def directory(self, **kwargs: Any) -> list[PatientRecord]:
        await asyncio.sleep(30)
        return []


SECOND_PATIENT = PatientRecord(
    patient_id="P00099",
    given_name="Luis",
    first_surname="Ruiz",
    second_surname="López",
    phone="+34612345678",
)


def make_ctx(settings, clinic: Any, from_number: str | None = "+34612345678") -> ToolContext:
    return ToolContext(
        call_id="CA-caller-id",
        now=NOW,
        from_number=from_number,
        clinic=clinic,
        log=CallLog("CA-caller-id"),
        submitter=None,
    )


def make_session(settings, call_id: str, from_number: str | None = "+34612345678") -> CallSession:
    params = {"from_number": from_number} if from_number else {}
    start = StartPayload(streamSid=f"MZ-{call_id}", callSid=call_id, customParameters=params)
    return CallSession.open(start, settings=settings, now=NOW)


def a_slot() -> Slot:
    return Slot(start=SLOT, provider_id="PR05", location_id="sur", appointment_type_id="review")


# --- the lookup ---------------------------------------------------------------


async def test_one_match_names_the_owner_of_the_line(offline_settings) -> None:
    """The commonest case: the dialling number is on exactly one record."""
    clinic = DirectoryStub([FAKE_PATIENT])
    ctx = make_ctx(offline_settings, clinic)

    match = await resolve_caller_line(ctx)

    assert match.looked_up is True
    assert match.patient == FAKE_PATIENT
    assert match.from_number == "+34612345678"
    # The phone is the only filter: a name we have not heard yet would exclude
    # the very record we are looking for.
    assert clinic.queries == [
        {"name": None, "national_id": None, "phone": "+34612345678", "date_of_birth": None}
    ]


async def test_one_match_is_remembered_as_who_was_on_the_line(offline_settings) -> None:
    """Problem 9 needs to know who called even after a third party is booked."""
    ctx = make_ctx(offline_settings, DirectoryStub([FAKE_PATIENT]))

    await resolve_caller_line(ctx)

    assert ctx.state[CALLER_IDENTITY_KEY] == {
        "patient_id": FAKE_PATIENT.patient_id,
        "matched_on": ["from_number"],
    }


async def test_no_match_is_the_new_patient_signal(offline_settings) -> None:
    """A line on no record is the one thing that reliably means "not registered"."""
    match = await resolve_caller_line(make_ctx(offline_settings, DirectoryStub([])))

    assert match.looked_up is True
    assert match.patient is None
    assert match.candidates == []


async def test_a_shared_line_identifies_nobody(offline_settings) -> None:
    """Two records on one phone is a family, not an identification."""
    clinic = DirectoryStub([FAKE_PATIENT, SECOND_PATIENT])

    match = await resolve_caller_line(make_ctx(offline_settings, clinic))

    assert match.looked_up is True
    assert match.patient is None
    assert len(match.candidates) == 2


async def test_a_withheld_number_is_not_looked_up(offline_settings) -> None:
    clinic = DirectoryStub([FAKE_PATIENT])

    match = await resolve_caller_line(make_ctx(offline_settings, clinic, from_number=None))

    assert match.looked_up is False
    assert match.patient is None
    assert clinic.queries == []


async def test_a_directory_that_is_down_never_breaks_the_call(offline_settings) -> None:
    """Worst case is the call we had before: the model asks who they are."""
    ctx = make_ctx(offline_settings, BrokenDirectory())

    match = await resolve_caller_line(ctx)

    assert match.looked_up is False
    assert caller_note_for(match) == ""


# --- the session --------------------------------------------------------------


async def test_the_session_remembers_the_line(offline_settings, monkeypatch) -> None:
    session = make_session(offline_settings, "CA-line")
    monkeypatch.setattr(session.ctx, "clinic", DirectoryStub([FAKE_PATIENT]))

    match = await session.resolve_caller_line()

    assert match.patient == FAKE_PATIENT
    assert session.memory.caller_line == match
    assert session.memory.line_owner == FAKE_PATIENT


async def test_a_slow_directory_does_not_hold_the_greeting(offline_settings, monkeypatch) -> None:
    """The note is never worth a silent line: past the timeout the call opens without it."""
    session = make_session(offline_settings, "CA-slow")
    monkeypatch.setattr(session.ctx, "clinic", SlowDirectory())
    session.settings = dataclasses.replace(offline_settings, caller_id_lookup_timeout_secs=0.01)

    started = asyncio.get_running_loop().time()
    match = await session.resolve_caller_line()
    elapsed = asyncio.get_running_loop().time() - started

    assert match.looked_up is False
    assert elapsed < 5
    assert caller_note_for(session.memory.caller_line) == ""


# --- the fallback -------------------------------------------------------------


def test_the_line_owner_books_when_the_conversation_named_nobody() -> None:
    """A slot was found for this call, so the alternative is a refusal worth nothing."""
    memory = CallMemory()
    memory.caller_line = CallerLineMatch(
        looked_up=True, from_number="+34612345678", patient=FAKE_PATIENT
    )
    assert memory.draft_booking() is None  # no slot yet

    memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    draft = memory.draft_booking()

    assert draft is not None
    assert draft.patient_id == FAKE_PATIENT.patient_id


def test_the_conversation_outranks_the_line() -> None:
    """A third-party call books the patient, never the phone's owner."""
    memory = CallMemory()
    memory.caller_line = CallerLineMatch(looked_up=True, patient=FAKE_PATIENT)
    memory.observe("find_patient", FindPatientResult(status="found", patient=SECOND_PATIENT))
    memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))

    draft = memory.draft_booking()

    assert draft is not None
    assert draft.patient_id == SECOND_PATIENT.patient_id


def test_a_line_on_no_record_drafts_nothing() -> None:
    memory = CallMemory()
    memory.caller_line = CallerLineMatch(looked_up=True, from_number="+34600000000")
    memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))

    assert memory.draft_booking() is None


def test_an_open_lookup_still_blocks_the_draft() -> None:
    """Two namesakes and no second field: the line owner does not settle it."""
    memory = CallMemory()
    memory.caller_line = CallerLineMatch(looked_up=True, patient=FAKE_PATIENT)
    memory.observe("find_slots", AvailabilityResult(slots=[a_slot()]))
    memory.observe("find_patient", FindPatientResult(status="ambiguous", ask_for="date_of_birth"))

    assert memory.draft_booking() is None


# --- the prompt ---------------------------------------------------------------


def test_the_note_names_the_caller_and_their_id() -> None:
    note = caller_note_for(CallerLineMatch(looked_up=True, patient=FAKE_PATIENT))

    assert "Marta Ruiz López" in note
    assert "P00042" in note
    assert "insurer=sanitas" in note
    assert "visited_before=true" in note


def test_the_note_keeps_protected_fields_off_the_model_s_desk() -> None:
    """Problem 14 scans our turns for these. What is not in the prompt cannot slip out."""
    note = caller_note_for(CallerLineMatch(looked_up=True, patient=FAKE_PATIENT))

    assert FAKE_PATIENT.national_id not in note
    assert "1985-03-12" not in note
    assert FAKE_PATIENT.email not in note


def test_the_note_hands_over_a_new_patient_s_phone() -> None:
    """The 90 seconds spent dictating a number we already had, on 2026-09-19."""
    note = caller_note_for(CallerLineMatch(looked_up=True, from_number="+34610602036"))

    assert "+34610602036" in note
    assert "never ask for it" in note
    assert "new patient" in note


def test_a_shared_line_says_nothing_to_the_model() -> None:
    note = caller_note_for(
        CallerLineMatch(looked_up=True, candidates=[FAKE_PATIENT, SECOND_PATIENT])
    )

    assert FAKE_PATIENT.patient_id not in note
    assert SECOND_PATIENT.patient_id not in note


def test_no_lookup_leaves_the_prompt_exactly_as_it_was() -> None:
    """A call with no caller id must read the prompt it read before this existed."""
    plain = build_system_prompt(NOW)

    assert caller_note_for(None) == ""
    assert build_system_prompt(NOW, caller=CallerLineMatch()) == plain
    assert initial_messages(NOW)[0]["content"] == plain


def test_the_note_reaches_the_model() -> None:
    match = CallerLineMatch(looked_up=True, patient=FAKE_PATIENT)

    content = initial_messages(NOW, caller=match)[0]["content"]

    assert "CALLER." in content
    assert "P00042" in content
    # Before FLOW, so the identification rules are read knowing who called.
    assert content.index("CALLER.") < content.index("FLOW.")


def test_the_prompt_with_a_note_still_fits_a_turn() -> None:
    """The note buys back far more clock than it spends, but it is not free either.

    ``tests/test_prompt.py`` owns the *static* budget of 1,650 tokens. The CALLER
    block is a per-call addition on top of it, resent every turn like the rest of
    the prompt: measured against the live directory it costs 130-160 tokens, the
    bulk of it the chart note. That buys back the two-to-six opening turns the
    call used to spend asking who is speaking, at ~4.5 s of judged latency each,
    so the trade is worth several times its price.

    The ceiling below is the worst case with the longest chart note in the live
    set plus room to spare. The chart note is never truncated to hit it: the
    operative sentence tends to come last ("...who may not know the insurer --
    ask"), so a trimmed note would drop the very instruction it exists for.
    """
    loaded = FAKE_PATIENT.model_copy(
        update={
            "referrals": ["orthopaedics", "dermatology", "physiotherapy"],
            "note": (
                "Lapsed -- the chart stops at December 2024. Eight visits on the chart, "
                "spread across gynaecology, physiotherapy, general practice and "
                "dermatology. Holds a referral for Dermatology; no need to ask for one. "
                "Mishears numbers said at speed."
            ),
        }
    )
    text = build_system_prompt(NOW, caller=CallerLineMatch(looked_up=True, patient=loaded))

    assert len(text) // 4 <= 1800


def test_the_note_adds_nothing_the_record_did_not_carry() -> None:
    """The block's size is the record's size: it cannot grow on its own."""
    spare = PatientRecord(patient_id="P00001", given_name="Ana", first_surname="Gil")
    note = caller_note_for(CallerLineMatch(looked_up=True, patient=spare))

    assert "insurer=" not in note
    assert "referrals=" not in note
    assert "note=" not in note
    assert len(note) < 300


def test_the_flow_no_longer_waits_for_a_second_identifier() -> None:
    """The instruction that cost three cases: a name alone is enough to look up."""
    text = build_system_prompt(NOW)

    assert "a name alone is" in text
    assert "Never wait for a second identifier." in text


# --- the live directory, on the fixtures --------------------------------------


async def test_the_fixture_directory_resolves_a_line_end_to_end(offline_settings) -> None:
    """No stub: the offline clinic, queried by phone exactly as the live one is."""
    session = make_session(offline_settings, "CA-fixture", from_number="+34711330529")

    match = await session.resolve_caller_line()

    assert match.looked_up is True
    assert match.patient is not None
    assert match.patient.patient_id == "P00001"
    assert match.patient.date_of_birth == date(2001, 9, 19)
    assert "Josefa" in caller_note_for(match)


async def test_the_fixtures_own_shared_line_identifies_nobody(offline_settings) -> None:
    """+34612345678 is a mother and her child. Booking either off the line is a guess."""
    session = make_session(offline_settings, "CA-family", from_number="+34612345678")

    match = await session.resolve_caller_line()

    assert len(match.candidates) == 2
    assert match.patient is None
    assert session.memory.line_owner is None
    assert caller_note_for(match) == ""
