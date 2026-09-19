"""``call.intent``: the caller's goal, logged when a domain tool reveals it.

No tool asks the model "what does the caller want" - the classification lives
inside the model, so the session logs the intent the first time a tool call
can only mean one thing: a ``prepare_*`` names its action, an emergency
``triage`` means escalate, and ``submit_action`` carries the vocabulary
itself. These tests drive ``CallSession.call_tool`` like the voice pipeline
does, with no socket and no model.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from vortex.contract import MADRID, Action, SubmitResult, action_payload, action_route
from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload

NOW = datetime(2026, 9, 18, 10, 0, tzinfo=MADRID)
MOTHER = "P00042"


class AcceptingSubmitter:
    """A submit client the platform always answers 200 to."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="accepted", http_status=200)

    async def aclose(self) -> None:
        return None


def make_session(settings, call_id: str = "CA-intent") -> CallSession:
    start = StartPayload(streamSid=f"MZ-{call_id}", callSid=call_id, customParameters={})
    session = CallSession.open(start, settings=settings, now=NOW)
    session.submitter = session.ctx.submitter = AcceptingSubmitter()
    return session


def intents(settings, call_id: str) -> list[dict[str, Any]]:
    path = Path(settings.calls_log_path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return [x for x in lines if x["call_id"] == call_id and x["kind"] == "call.intent"]


async def test_emergency_triage_says_escalate(offline_settings) -> None:
    session = make_session(offline_settings)
    await session.call_tool("triage", {"complaint": "me duele el pecho y no puedo respirar"})
    logged = intents(offline_settings, session.call_id)
    assert [x["intent"] for x in logged] == ["escalate"]
    assert logged[0]["tool"] == "triage"


async def test_a_routing_triage_says_nothing(offline_settings) -> None:
    """A specialty answer is routing, not a goal: no intent is logged."""
    session = make_session(offline_settings)
    await session.call_tool("triage", {"complaint": "quiero una revisión general"})
    assert intents(offline_settings, session.call_id) == []


async def test_prepare_tools_reveal_and_reclassify(offline_settings) -> None:
    """cancel first, then book: each re-classification logs a new intent."""
    session = make_session(offline_settings)
    caller = await session.call_tool(
        "find_patient", {"name": "Marta Ruiz López", "date_of_birth": "1985-03-12"}
    )
    assert caller.status == "found"

    # She wants her appointment cancelled: prepare_cancel reveals it.
    appointments = await session.call_tool("list_appointments", {"patient_id": MOTHER})
    assert appointments.appointments
    appointment_id = appointments.appointments[0].appointment_id
    await session.call_tool(
        "prepare_cancel", {"appointment_id": appointment_id, "patient_id": MOTHER}
    )
    assert [x["intent"] for x in intents(offline_settings, session.call_id)] == ["cancel"]

    # Then she changes her mind and asks for a new booking instead.
    day = (NOW + timedelta(days=1)).date()
    availability = await session.call_tool(
        "find_slots",
        {
            "patient_id": MOTHER,
            "specialty_id": "general_practice",
            "date_from": day.isoformat(),
            "date_to": day.isoformat(),
        },
    )
    assert availability.slots
    slot = availability.slots[0]
    booking = await session.call_tool(
        "prepare_booking",
        {"patient_id": MOTHER, "slot": slot.model_dump(mode="json"), "policy_id": "sanitas"},
    )
    assert booking.rejection is None
    assert [x["intent"] for x in intents(offline_settings, session.call_id)] == [
        "cancel",
        "book",
    ]

    # The submission carries the vocabulary itself: no mapping needed.
    await session.call_tool(
        "submit_action", {"action": {"kind": "book", **booking.action.model_dump(mode="json")}}
    )
    logged = intents(offline_settings, session.call_id)
    # Same intent twice in a row logs once - a repeat is not a re-classification.
    assert [x["intent"] for x in logged] == ["cancel", "book"]
    await session.close()


async def test_the_fallback_submit_notes_what_the_call_ended_as(offline_settings) -> None:
    """A call that resolved nothing ends on a typed refusal; the submission
    the session sends itself still lands in the log as the final intent."""
    session = make_session(offline_settings, "CA-silent")
    await session.close(reason="stop")
    logged = intents(offline_settings, "CA-silent")
    assert logged[-1]["intent"] == "no-action"
    assert logged[-1]["tool"] == "session.submit"
