"""Problem 18 (the real call): two actions in one call, both correct.

``evals/conversation/scenarios/difficult.yaml`` has the scripted-caller version
of this (a grandmother moving her grandson's appointment and booking herself
one, changing her mind about the order). What that scenario can't isolate from
a real model's behaviour is whether the session/submit machinery itself
handles two actions cleanly — no partial credit if only one lands, and no
cross-contamination between the two patients involved. This drives the same
tool calls a conversation would, through ``CallSession.call_tool`` exactly
like the voice pipeline does, with no socket and no model.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from vortex.contract import MADRID, Action, SubmitResult, action_payload, action_route
from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)
MOTHER = "P00042"
CHILD = "P00107"


class AcceptingSubmitter:
    """A submit client the platform always answers 200 to."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="accepted", http_status=200)

    async def aclose(self) -> None:
        return None


def make_session(settings) -> CallSession:
    start = StartPayload(streamSid="MZ-real-call", callSid="CA-real-call", customParameters={})
    session = CallSession.open(start, settings=settings, now=NOW)
    submitter = AcceptingSubmitter()
    session.submitter = session.ctx.submitter = submitter
    return session


async def test_a_reschedule_and_a_new_booking_both_land_in_one_call(offline_settings) -> None:
    """Book first, then change your mind and move the child's appointment too —
    the order a real caller does it, reversed from the order they said it in."""
    session = make_session(offline_settings)

    # First identify the caller and book herself an appointment.
    caller = await session.call_tool(
        "find_patient",
        {"name": "Marta Ruiz López", "date_of_birth": "1985-03-12"},
    )
    assert caller.status == "found"

    day = (NOW + timedelta(days=1)).date()  # Saturday: only Centro opens
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
    await session.call_tool(
        "submit_action", {"action": {"kind": "book", **booking.action.model_dump(mode="json")}}
    )

    # Then, mid-call, also move her son's existing appointment.
    child = await session.call_tool(
        "find_patient", {"name": "Lucas Ruiz López", "date_of_birth": "2018-06-20"}
    )
    assert child.status == "found"

    appointments = await session.call_tool("list_appointments", {"patient_id": CHILD})
    assert appointments.appointments
    appointment_id = appointments.appointments[0].appointment_id

    new_slot = {
        "start": datetime(2026, 10, 5, 17, 15, tzinfo=MADRID).isoformat(),
        "provider_id": "PR03",
        "location_id": "centro",
        "appointment_type_id": "review",
    }
    reschedule = await session.call_tool(
        "prepare_reschedule",
        {"appointment_id": appointment_id, "slot": new_slot, "policy_id": "sanitas"},
    )
    assert reschedule.rejection is None
    await session.call_tool(
        "submit_action",
        {"action": {"kind": "reschedule", **reschedule.action.model_dump(mode="json")}},
    )

    await session.close()

    sent = session.submitter.sent  # type: ignore[attr-defined]
    routes = [route for route, _ in sent]
    assert routes == [
        "/api/v1/submit/book",
        "/api/v1/submit/reschedule",
    ], "both actions, in the order actually submitted"

    book_payload = sent[0][1]
    reschedule_payload = sent[1][1]
    assert book_payload["patient_id"] == MOTHER
    assert reschedule_payload["appointment_id"] == appointment_id
    # Neither action borrowed the other patient's identity or appointment.
    assert "patient_id" not in reschedule_payload or reschedule_payload.get("patient_id") != CHILD
    assert book_payload["patient_id"] != CHILD
