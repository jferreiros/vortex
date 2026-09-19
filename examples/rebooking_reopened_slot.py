"""Example: queue a no-availability call and draft it when a slot reopens.

Run with:

    uv run python examples/rebooking_reopened_slot.py

The reopened slot represents another client cancelling or moving their booking.
No platform submit is made here; the output is an ops draft for follow-up.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from vortex.clinic.client import FakeClinicClient
from vortex.contract import AvailabilityResponse
from vortex.diary.rebooking import RebookingStore, RebookingWatcher, analyze_call


class ReopeningClinic(FakeClinicClient):
    def __init__(self) -> None:
        super().__init__()
        self.reopened = False

    async def availability(self, **kwargs: Any) -> AvailabilityResponse:
        answer = await super().availability(**kwargs)
        return answer if self.reopened else answer.model_copy(update={"slots": []})


def no_availability_call() -> list[dict[str, Any]]:
    call_id = "CA-rebooking-example"
    return [
        {"kind": "call.started", "call_id": call_id},
        {
            "kind": "turn.user",
            "call_id": call_id,
            "text": "I need the earliest general practice appointment on Saturday.",
        },
        {
            "kind": "tool.returned",
            "call_id": call_id,
            "tool": "find_patient",
            "result": {
                "status": "found",
                "patient": {
                    "patient_id": "P00042",
                    "given_name": "Marta",
                    "first_surname": "Ruiz",
                    "insurer": "sanitas",
                    "has_visited_before": True,
                },
            },
        },
        {
            "kind": "tool.called",
            "call_id": call_id,
            "tool": "find_slots",
            "args": {
                "patient_id": "P00042",
                "specialty_id": "general_practice",
                "date_from": "2026-09-19",
                "date_to": "2026-09-19",
            },
        },
        {
            "kind": "tool.returned",
            "call_id": call_id,
            "tool": "find_slots",
            "result": {
                "slots": [],
                "blocked": [],
                "appointment_type": None,
                "rejection": {"reason": "no_availability"},
            },
        },
        {
            "kind": "call.summary",
            "call_id": call_id,
            "actions": [
                {
                    "route": "/api/v1/submit/no-action",
                    "payload": {"call_id": call_id, "reason": "no_availability"},
                    "result": {"status": "accepted"},
                }
            ],
        },
    ]


async def main() -> None:
    db = Path("logs/rebooking-example.sqlite3")
    db.unlink(missing_ok=True)

    request = analyze_call(no_availability_call())
    if request is None:
        raise RuntimeError("example call did not create a rebooking request")

    store = RebookingStore(db)
    store.add(request)

    clinic = ReopeningClinic()
    watcher = RebookingWatcher(clinic, store)
    print("Before another client cancels:", await watcher.check_once())

    clinic.reopened = True
    matched = await watcher.check_once()
    print("After another client cancels:")
    print(matched[0].draft_action.model_dump_json(indent=2) if matched else "no draft")


if __name__ == "__main__":
    asyncio.run(main())
