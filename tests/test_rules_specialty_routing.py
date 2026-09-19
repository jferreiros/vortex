"""Where the specialty comes from when a caller names a doctor.

General practice is the triage table's residue for a complaint it does not
recognise, and the 2026-09-19 run showed the cost: a wrist and "Dr. Iglesia"
went out as ``general_practice``, so the call searched a GP agenda for an
orthopaedic surgeon. A doctor the catalogue knows outranks that residue, in
``triage`` and in ``find_provider`` alike.
"""

from __future__ import annotations

import json
from datetime import datetime

from vortex.clinic.client import FakeClinicClient
from vortex.contract import MADRID, FindProviderInput, ToolContext, TriageInput
from vortex.observability.calllog import CallLog
from vortex.rules.tools import find_provider, triage
from vortex.rules.triage import route

#: Dr. Iglesia (orthopaedics) against Dra. Iglesias (dermatology).
ORTHOPAEDIC_PROVIDER_ID = "PR05"


def make_ctx(tmp_path) -> ToolContext:
    return ToolContext(
        call_id="CA-routing",
        now=datetime(2026, 9, 18, 9, 0, tzinfo=MADRID),
        from_number="+34612345678",
        clinic=FakeClinicClient(),
        log=CallLog("CA-routing", tmp_path / "calls.jsonl"),
    )


async def test_a_wrist_with_a_named_orthopaedic_doctor_is_never_general_practice(tmp_path):
    """The failure itself: wrist + Dr. Iglesia searched as a GP."""
    ctx = make_ctx(tmp_path)

    result = await triage(
        ctx, TriageInput(complaint="I fell on my wrist and it hurts", provider_name="Dr. Iglesia")
    )

    assert result.specialty_id == "orthopaedics"
    assert result.provider_id == ORTHOPAEDIC_PROVIDER_ID
    assert not result.emergency


async def test_a_named_doctor_decides_a_complaint_the_table_does_not_recognise(tmp_path):
    """Nothing published routes "it is my usual check" — the doctor does."""
    ctx = make_ctx(tmp_path)

    result = await triage(
        ctx, TriageInput(complaint="it is my usual check", provider_name="doctor Iglesia")
    )

    assert result.specialty_id == "orthopaedics"


async def test_the_table_still_answers_when_the_name_is_nobody_in_the_catalogue(tmp_path):
    ctx = make_ctx(tmp_path)

    result = await triage(
        ctx, TriageInput(complaint="sore throat for three days", provider_name="doctor Vilar")
    )

    assert result.specialty_id == "general_practice"
    assert result.provider_id is None


async def test_a_name_spanning_two_specialties_leaves_the_complaint_to_answer(tmp_path):
    """A mis-heard Iglesi is Iglesia and Iglesias at once: a doctor who cannot be
    resolved decides nothing, and the published row still routes the complaint."""
    ctx = make_ctx(tmp_path)

    result = await triage(
        ctx, TriageInput(complaint="my knee locks going up stairs", provider_name="Iglesi")
    )

    assert result.specialty_id == "orthopaedics"
    assert result.provider_id is None


async def test_an_emergency_outranks_the_named_doctor(tmp_path):
    ctx = make_ctx(tmp_path)

    result = await triage(
        ctx,
        TriageInput(
            complaint="tight pain across the chest and cannot catch my breath",
            provider_name="Dr. Iglesia",
        ),
    )

    assert result.emergency
    assert result.specialty_id is None
    assert result.rejection is not None
    assert result.rejection.reason == "medical_emergency"


async def test_find_provider_reports_the_doctor_a_guessed_specialty_would_hide(tmp_path):
    """A specialty_id that matches nobody of that name is a guess: the doctor
    exists, and the match carries the specialty they really consult in."""
    ctx = make_ctx(tmp_path)

    match = await find_provider(
        ctx, FindProviderInput(spoken_name="Dr. Iglesia", specialty_id="general_practice")
    )

    assert match.status == "found"
    assert match.provider is not None
    assert match.provider.provider_id == ORTHOPAEDIC_PROVIDER_ID
    assert match.provider.specialty_id == "orthopaedics"


async def test_a_specialty_that_does_split_a_near_miss_pair_still_splits_it(tmp_path):
    """The fallback never loosens the Iglesias/Iglesia or Sáez/Sáenz split."""
    ctx = make_ctx(tmp_path)

    dermatologist = await find_provider(
        ctx, FindProviderInput(spoken_name="Iglesias", specialty_id="dermatology")
    )
    paediatrician = await find_provider(
        ctx, FindProviderInput(spoken_name="Sáenz", specialty_id="paediatrics")
    )

    assert dermatologist.status == "found"
    assert dermatologist.provider is not None
    assert dermatologist.provider.provider_id == "PR04"
    assert paediatrician.status == "found"
    assert paediatrician.provider is not None
    assert paediatrician.provider.provider_id == "PR03"


async def test_an_unknown_doctor_is_still_not_found(tmp_path):
    ctx = make_ctx(tmp_path)

    match = await find_provider(
        ctx, FindProviderInput(spoken_name="doctor Vilar", specialty_id="general_practice")
    )

    assert match.status == "not_found"
    assert match.rejection is not None
    assert match.rejection.reason == "provider_not_found"


# ---- the specialty the caller names outright --------------------------------
#
# The same residue, reached the other way. The table holds symptoms, so it
# scores nothing for the word "gynaecology": ten calls in one night asked for a
# specialty by name and were routed to a GP, and the ones that lost the case are
# exactly the ones that then booked a general-practice appointment type.


async def test_a_named_specialty_is_never_the_general_practice_residue(tmp_path):
    """The 3-point failure of run 1d45754d, in one line."""
    ctx = make_ctx(tmp_path)

    routed = await triage(
        ctx, TriageInput(complaint="the earliest gynaecology appointment, for contraception")
    )

    assert routed.specialty_id == "gynaecology"
    assert routed.emergency is False
    assert routed.rejection is None


async def test_every_specialty_answers_to_its_own_name(tmp_path):
    ctx = make_ctx(tmp_path)
    for complaint, specialty in (
        ("I need a gynecology appointment for my yearly checkup", "gynaecology"),
        ("can I see a dermatologist about this", "dermatology"),
        ("I was told to book orthopaedics", "orthopaedics"),
        ("physiotherapy, please", "physiotherapy"),
        ("necesito cita con el ginecologo", "gynaecology"),
        ("vull anar al dermatoleg", "dermatology"),
        ("fisioterapia para la espalda", "physiotherapy"),
    ):
        routed = await triage(ctx, TriageInput(complaint=complaint))
        assert routed.specialty_id == specialty, complaint


async def test_a_named_specialty_outranks_a_symptom_that_disagrees(tmp_path):
    """They asked for the physiotherapist. The knee row does not overrule them."""
    ctx = make_ctx(tmp_path)

    routed = await triage(
        ctx, TriageInput(complaint="my knee clicks going up stairs, can I see a physiotherapist?")
    )

    assert routed.specialty_id == "physiotherapy"


async def test_a_child_still_goes_to_paediatrics_whatever_was_named(tmp_path):
    """The table's own invariant, and the age rule behind it, both survive."""
    ctx = make_ctx(tmp_path)

    routed = await triage(
        ctx, TriageInput(complaint="my daughter needs to see a dermatologist about a rash")
    )

    assert routed.specialty_id == "paediatrics"


async def test_a_named_doctor_still_outranks_a_named_specialty(tmp_path):
    """Dr. Iglesia consults in orthopaedics; that is the only agenda he has."""
    ctx = make_ctx(tmp_path)

    routed = await triage(
        ctx,
        TriageInput(complaint="a dermatology appointment please", provider_name="Dr. Iglesia"),
    )

    assert routed.specialty_id == "orthopaedics"
    assert routed.provider_id == ORTHOPAEDIC_PROVIDER_ID


async def test_an_emergency_outranks_a_named_specialty(tmp_path):
    ctx = make_ctx(tmp_path)

    routed = await triage(
        ctx,
        TriageInput(
            complaint=(
                "I want a dermatology appointment but his face has dropped on one side "
                "and his arm has gone numb and his speech is slurred"
            )
        ),
    )

    assert routed.emergency is True
    assert routed.specialty_id is None
    assert routed.rejection is not None and routed.rejection.reason == "medical_emergency"


async def test_two_specialties_at_once_leave_the_table_to_answer(tmp_path):
    """Not a request that resolves. We do not pick one of the pair."""
    ctx = make_ctx(tmp_path)

    routed = await triage(
        ctx, TriageInput(complaint="a gynaecologist or a dermatologist, I am not sure which")
    )

    assert routed.specialty_id == "general_practice"


async def test_a_symptom_that_names_nothing_routes_exactly_as_it_did(tmp_path):
    """The regression guard: no symptom row moves. These are live complaints
    from calls that passed while the table answered them."""
    ctx = make_ctx(tmp_path)
    for complaint, specialty in (
        ("a mole on my back that looks different from last year", "general_practice"),
        ("dry, itchy skin", "general_practice"),
        ("rash on my arm that keeps coming back", "general_practice"),
        ("lower back sore for a month, not getting better", "general_practice"),
        ("shoulder problem, needs orthopedics", "orthopaedics"),
        ("my son has been pulling at his ear and barely slept", "paediatrics"),
        ("very heavy, irregular periods for months", "gynaecology"),
        ("sore throat for three days", "general_practice"),
    ):
        routed = await triage(ctx, TriageInput(complaint=complaint))
        assert routed.specialty_id == specialty, complaint


async def test_the_override_is_logged_with_what_the_table_had_said(tmp_path):
    ctx = make_ctx(tmp_path)
    await triage(ctx, TriageInput(complaint="a gynaecology appointment"))

    events = [
        json.loads(line)
        for line in ctx.log.path.read_text().splitlines()
        if line.strip() and "triage.specialty_named_by_caller" in line
    ]
    assert events
    assert events[-1]["specialty_id"] == "gynaecology"
    assert events[-1]["table_said"] == "general_practice"


# ---- when the model paraphrases the specialty away --------------------------
#
# All six live calls that said "I need a dermatology appointment, about a mole on
# my back" reached triage as the mole alone. The one that passed submitted
# dermatology_review anyway; the ones that lost submitted a GP review. So the
# caller's own turns decide it, but only where the table recognised nothing.


def caller_said(ctx: ToolContext, *turns: str) -> None:
    for turn in turns:
        ctx.log.user_turn(turn)


async def test_the_caller_s_own_words_answer_when_the_model_drops_the_specialty(tmp_path):
    """The 3-point failure of run 023ba365, in one line."""
    ctx = make_ctx(tmp_path)
    caller_said(ctx, "I need a dermatology appointment, about a mole on my back")

    routed = await triage(
        ctx, TriageInput(complaint="a mole on my back that looks different from last year")
    )

    assert routed.specialty_id == "dermatology"


async def test_a_complaint_the_table_recognises_is_still_the_table_s_to_answer(tmp_path):
    """A specialty mentioned in passing never outranks a symptom that scored."""
    ctx = make_ctx(tmp_path)
    caller_said(ctx, "I saw the dermatologist last year", "but now my knee locks going up stairs")

    routed = await triage(ctx, TriageInput(complaint="my knee locks going up stairs"))

    assert routed.specialty_id == "orthopaedics"


async def test_a_scoring_general_practice_row_is_not_overridden_from_the_transcript(tmp_path):
    """'sore throat' is a published GP row, not the residue. It stands."""
    ctx = make_ctx(tmp_path)
    caller_said(ctx, "my daughter saw a dermatologist once", "I have a sore throat for three days")

    routed = await triage(ctx, TriageInput(complaint="sore throat for three days"))

    assert routed.specialty_id == "general_practice"


async def test_a_child_in_the_transcript_vetoes_the_override(tmp_path):
    """The specialty came out of the transcript, so the child guard reads it too.

    It vetoes rather than redirects: routing a child to paediatrics off words the
    complaint never carried is a separate question, and this leaves that answer
    exactly as it is today.
    """
    ctx = make_ctx(tmp_path)
    caller_said(ctx, "my daughter needs to see a dermatologist about a rash on her arm")

    routed = await triage(ctx, TriageInput(complaint="a rash on her arm"))

    assert routed.specialty_id != "dermatology"
    assert routed.specialty_id == route("a rash on her arm")


async def test_a_silent_transcript_changes_nothing(tmp_path):
    """No turns recorded: exactly the answer the table gave before."""
    ctx = make_ctx(tmp_path)

    routed = await triage(ctx, TriageInput(complaint="a mole on my back"))

    assert routed.specialty_id == "general_practice"


async def test_the_complaint_still_wins_over_the_transcript(tmp_path):
    """Last stated request: what they are calling about now, not what they said first."""
    ctx = make_ctx(tmp_path)
    caller_said(ctx, "I thought I needed a dermatologist")

    routed = await triage(ctx, TriageInput(complaint="actually a gynaecology appointment please"))

    assert routed.specialty_id == "gynaecology"


async def test_the_transcript_override_says_where_it_came_from(tmp_path):
    ctx = make_ctx(tmp_path)
    caller_said(ctx, "the earliest physiotherapy appointment you have")
    await triage(ctx, TriageInput(complaint="my back has been sore"))

    events = [
        json.loads(line)
        for line in ctx.log.path.read_text().splitlines()
        if line.strip() and "triage.specialty_named_by_caller" in line
    ]
    assert events[-1]["specialty_id"] == "physiotherapy"
    assert events[-1]["from_transcript"] is True
