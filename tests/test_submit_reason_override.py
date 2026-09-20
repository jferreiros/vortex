"""The submitted ``reason`` is the rules' verdict, not the model's paraphrase.

Call ``c9f087a0`` of the 19 Sep run: ``check_eligibility`` answered
``location_not_covered`` (ASISA does not cover physiotherapy at that site) and
the model submitted ``specialty_not_covered``. Scoring reads a closed
vocabulary, so the near neighbour scored zero.

Everything here runs offline: no key, no socket, a fake submit client.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from vortex.contract import (
    MADRID,
    Action,
    AvailabilityResult,
    BlockedProvider,
    BookAction,
    EligibilityVerdict,
    ProviderMatch,
    Rejection,
    Slot,
    SubmitResult,
    action_payload,
    action_route,
)
from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload

NOW = datetime(2026, 9, 19, 10, 0, tzinfo=MADRID)
SLOT = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)


class AcceptingSubmitter:
    """A submit client the platform always answers 200 to."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="accepted", http_status=200)

    async def aclose(self) -> None:
        return None


def make_session(settings, call_id: str) -> tuple[CallSession, AcceptingSubmitter]:
    start = StartPayload(streamSid=f"MZ-{call_id}", callSid=call_id, customParameters={})
    session = CallSession.open(start, settings=settings, now=NOW)
    submitter = AcceptingSubmitter()
    session.submitter = session.ctx.submitter = submitter
    return session, submitter


def events(written: list[dict[str, Any]], call_id: str, kind: str) -> list[dict[str, Any]]:
    return [x for x in written if x["call_id"] == call_id and x["kind"] == kind]


def blocked_on_location() -> EligibilityVerdict:
    return EligibilityVerdict(
        allowed=False,
        rejection=Rejection(
            reason="location_not_covered",
            detail="asisa does not cover physiotherapy at this site",
        ),
    )


async def test_the_eligibility_verdict_beats_the_models_reason(
    offline_settings, _stub_call_events
) -> None:
    """The c9f087a0 failure: tool said location_not_covered, model said specialty."""
    session, submitter = make_session(offline_settings, "CA-c9f087a0")
    session.memory.observe("check_eligibility", blocked_on_location())

    await session.call_tool(
        "submit_action", {"action": {"kind": "no-action", "reason": "specialty_not_covered"}}
    )

    route, payload = submitter.sent[0]
    assert route == "/api/v1/submit/no-action"
    assert payload["reason"] == "location_not_covered"
    (override,) = events(_stub_call_events, "CA-c9f087a0", "submit.reason_override")
    assert override["model_reason"] == "specialty_not_covered"
    assert override["reason"] == "location_not_covered"
    assert events(_stub_call_events, "CA-c9f087a0", "submit.sent")[0]["payload"]["reason"] == (
        "location_not_covered"
    )


async def test_a_blocked_provider_is_the_verdict_too(offline_settings) -> None:
    session, submitter = make_session(offline_settings, "CA-blocked")
    session.memory.observe(
        "find_slots",
        AvailabilityResult(
            slots=[], blocked=[BlockedProvider(provider_id="PR05", reason="provider_on_leave")]
        ),
    )

    await session.call_tool(
        "submit_action", {"action": {"kind": "no-action", "reason": "no_availability"}}
    )

    assert submitter.sent[0][1]["reason"] == "provider_on_leave"


async def test_every_tool_refusal_is_the_verdict(offline_settings, _stub_call_events) -> None:
    """A typed Rejection from any tool, not only the rules' two, is what we submit."""
    session, submitter = make_session(offline_settings, "CA-any-tool")
    session.memory.observe(
        "find_provider",
        ProviderMatch(status="not_found", rejection=Rejection(reason="provider_not_found")),
    )

    await session.call_tool(
        "submit_action", {"action": {"kind": "no-action", "reason": "out_of_scope"}}
    )

    assert submitter.sent[0][1]["reason"] == "provider_not_found"
    (override,) = events(_stub_call_events, "CA-any-tool", "submit.reason_override")
    assert override["model_reason"] == "out_of_scope"


async def test_an_escalation_keeps_its_verb(offline_settings) -> None:
    """The reason is forced; the route the model chose is not touched."""
    session, submitter = make_session(offline_settings, "CA-escalate")
    session.memory.observe("check_eligibility", blocked_on_location())

    await session.call_tool(
        "submit_action", {"action": {"kind": "escalate", "reason": "out_of_scope"}}
    )

    route, payload = submitter.sent[0]
    assert route == "/api/v1/submit/escalate"
    assert payload["reason"] == "location_not_covered"


async def test_a_booking_is_never_rewritten(offline_settings, _stub_call_events) -> None:
    """Only NO_ACTION and ESCALATE carry a reason; a BOOK goes out untouched."""
    session, submitter = make_session(offline_settings, "CA-book")
    session.memory.last_verdict = Rejection(reason="location_not_covered")
    booking = BookAction(
        patient_id="P00042",
        provider_id="PR05",
        location_id="sur",
        appointment_type_id="review",
        slot=SLOT,
        policy_id="asisa",
    )

    await session.submit(booking)

    route, payload = submitter.sent[0]
    assert route == "/api/v1/submit/book"
    assert "reason" not in payload
    assert events(_stub_call_events, "CA-book", "submit.reason_override") == []


async def test_without_a_verdict_the_model_decides(offline_settings, _stub_call_events) -> None:
    """No tool refused, so there is no reason to force and the model's stands."""
    session, submitter = make_session(offline_settings, "CA-no-verdict")
    session.memory.observe("triage", EligibilityVerdict(allowed=True))

    await session.call_tool(
        "submit_action", {"action": {"kind": "no-action", "reason": "out_of_scope"}}
    )

    assert submitter.sent[0][1]["reason"] == "out_of_scope"
    assert events(_stub_call_events, "CA-no-verdict", "submit.reason_override") == []


async def test_free_slots_drop_the_verdict(offline_settings) -> None:
    """Whatever blocked us no longer stands, so the model's reason stands."""
    session, submitter = make_session(offline_settings, "CA-cleared")
    session.memory.observe("check_eligibility", blocked_on_location())
    session.memory.observe(
        "find_slots",
        AvailabilityResult(
            slots=[
                Slot(
                    start=SLOT,
                    provider_id="PR05",
                    location_id="sur",
                    appointment_type_id="review",
                )
            ]
        ),
    )

    assert session.memory.last_verdict is None
    await session.call_tool(
        "submit_action", {"action": {"kind": "no-action", "reason": "no_availability"}}
    )

    assert submitter.sent[0][1]["reason"] == "no_availability"


async def test_an_allowed_recheck_drops_the_verdict(offline_settings) -> None:
    """The caller moved site: the rule that bit is gone, so it names nothing."""
    session, submitter = make_session(offline_settings, "CA-rechecked")
    session.memory.observe("check_eligibility", blocked_on_location())
    session.memory.observe("check_eligibility", EligibilityVerdict(allowed=True))

    assert session.memory.last_verdict is None
    assert session.memory.stored_reason is None
    await session.call_tool(
        "submit_action", {"action": {"kind": "no-action", "reason": "no_availability"}}
    )

    assert submitter.sent[0][1]["reason"] == "no_availability"


async def test_the_session_records_the_action_that_went_out(offline_settings) -> None:
    """sent_actions drives the fallback's re-send check, so it must not lie."""
    session, _ = make_session(offline_settings, "CA-recorded")
    session.memory.observe("check_eligibility", blocked_on_location())

    await session.call_tool(
        "submit_action", {"action": {"kind": "no-action", "reason": "specialty_not_covered"}}
    )

    assert [a.reason for a in session.sent_actions] == ["location_not_covered"]
