from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import httpx

from vortex.clinic.client import ClinicApiError, FakeClinicClient
from vortex.contract import MADRID, AvailabilityResponse, BookAction, RescheduleAction
from vortex.diary.rebooking import (
    RebookingStore,
    RebookingWatcher,
    analyze_call,
    analyze_calls,
    analyze_latest_call,
)

CALL_ID = "CA-no-slot"
PATIENT_ID = "P00042"
#: The day before the window every queued call in this module asked for.
NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)


class ReopeningClinic(FakeClinicClient):
    """A fake diary where another client's cancellation later exposes slots."""

    def __init__(self) -> None:
        super().__init__()
        self.reopened = False

    async def availability(self, **kwargs: Any) -> AvailabilityResponse:
        answer = await super().availability(**kwargs)
        if self.reopened:
            return answer
        return answer.model_copy(update={"slots": []})


class RecordingClinic(FakeClinicClient):
    """A fake diary that remembers every window it was asked about."""

    def __init__(self) -> None:
        super().__init__()
        self.windows: list[tuple[date, date]] = []

    async def availability(self, **kwargs: Any) -> AvailabilityResponse:
        self.windows.append((kwargs["date_from"], kwargs["date_to"]))
        return await super().availability(**kwargs)


class UtcClinic(FakeClinicClient):
    """A fake diary that reports the same slots with a non-Madrid offset."""

    async def availability(self, **kwargs: Any) -> AvailabilityResponse:
        answer = await super().availability(**kwargs)
        slots = [
            slot.model_copy(update={"start": slot.start.astimezone(UTC)}) for slot in answer.slots
        ]
        return answer.model_copy(update={"slots": slots})


class FlakyClinic(FakeClinicClient):
    """A fake diary that rejects the first query of a run and answers the rest."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error
        self.calls = 0

    async def availability(self, **kwargs: Any) -> AvailabilityResponse:
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return await super().availability(**kwargs)


def _patient_result() -> dict[str, Any]:
    return {
        "status": "found",
        "patient": {
            "patient_id": PATIENT_ID,
            "given_name": "Marta",
            "first_surname": "Ruiz",
            "second_surname": "López",
            "insurer": "sanitas",
            "has_visited_before": True,
        },
    }


def _submitted_no_availability() -> dict[str, Any]:
    return {
        "kind": "submit.result",
        "call_id": CALL_ID,
        "route": "/api/v1/submit/no-action",
        "payload": {"call_id": CALL_ID, "reason": "no_availability"},
        "result": {"status": "dry_run"},
    }


def _summary_no_availability() -> dict[str, Any]:
    return {
        "kind": "call.summary",
        "call_id": CALL_ID,
        "actions": [
            {
                "route": "/api/v1/submit/no-action",
                "payload": {"call_id": CALL_ID, "reason": "no_availability"},
                "result": {"status": "dry_run"},
            }
        ],
    }


def _book_events() -> list[dict[str, Any]]:
    return [
        {"kind": "call.started", "call_id": CALL_ID},
        {
            "kind": "turn.user",
            "call_id": CALL_ID,
            "text": "I need the earliest general practice appointment on Saturday.",
        },
        {
            "kind": "tool.returned",
            "call_id": CALL_ID,
            "tool": "find_patient",
            "result": _patient_result(),
        },
        {
            "kind": "tool.called",
            "call_id": CALL_ID,
            "tool": "find_slots",
            "args": {
                "patient_id": PATIENT_ID,
                "specialty_id": "general_practice",
                "date_from": "2026-09-19",
                "date_to": "2026-09-19",
            },
        },
        {
            "kind": "tool.returned",
            "call_id": CALL_ID,
            "tool": "find_slots",
            "result": {
                "slots": [],
                "blocked": [],
                "appointment_type": None,
                "rejection": {"reason": "no_availability"},
            },
        },
        _submitted_no_availability(),
        _summary_no_availability(),
    ]


def _reschedule_events() -> list[dict[str, Any]]:
    events = _book_events()
    events[1] = {
        "kind": "turn.user",
        "call_id": CALL_ID,
        "text": "I need to move my appointment with Dra. Ortiz to Saturday.",
    }
    events.insert(
        3,
        {
            "kind": "tool.returned",
            "call_id": CALL_ID,
            "tool": "list_appointments",
            "result": {
                "appointments": [
                    {
                        "appointment_id": "A0001",
                        "patient_id": PATIENT_ID,
                        "provider_id": "PR01",
                        "location_id": "centro",
                        "appointment_type_id": "review",
                        "start": "2026-09-30T10:00:00+02:00",
                    }
                ]
            },
        },
    )
    search = events[4]["args"]
    search.pop("specialty_id")
    search["provider_id"] = "PR01"
    search["location_id"] = "centro"
    return events


def test_no_availability_call_becomes_pending_rebooking() -> None:
    request = analyze_call(_book_events())

    assert request is not None
    assert request.intent == "book"
    assert request.patient_id == PATIENT_ID
    assert request.policy_id == "sanitas"
    assert request.specialty_id == "general_practice"
    assert request.date_from == date(2026, 9, 19)


def test_solved_calls_are_not_queued() -> None:
    events = _book_events()
    events[-2] = {
        "kind": "submit.result",
        "call_id": CALL_ID,
        "route": "/api/v1/submit/book",
        "payload": {"call_id": CALL_ID, "patient_id": PATIENT_ID},
        "result": {"status": "dry_run"},
    }
    events[-1] = {
        "kind": "call.summary",
        "call_id": CALL_ID,
        "actions": [
            {
                "route": "/api/v1/submit/book",
                "payload": {"call_id": CALL_ID, "patient_id": PATIENT_ID},
                "result": {"status": "dry_run"},
            }
        ],
    }

    assert analyze_call(events) is None


def test_store_is_idempotent_when_the_same_call_is_analyzed_twice(tmp_path: Path) -> None:
    store = RebookingStore(tmp_path / "rebooking.sqlite3")
    [request] = analyze_calls(_book_events() + _book_events())

    first = store.add(request)
    second = store.add(request)

    assert first.request_id == second.request_id
    assert [item.request_id for item in store.pending()] == [request.request_id]


def test_latest_call_helper_only_queues_the_last_call() -> None:
    earlier = [event | {"call_id": "CA-earlier"} for event in _book_events()]
    later = _book_events()

    request = analyze_latest_call(earlier + later)

    assert request is not None
    assert request.call_id == CALL_ID


async def test_reopened_slot_creates_draft_booking(tmp_path: Path) -> None:
    store = RebookingStore(tmp_path / "rebooking.sqlite3")
    request = analyze_call(_book_events())
    assert request is not None
    store.add(request)
    clinic = ReopeningClinic()
    watcher = RebookingWatcher(clinic, store)

    assert await watcher.check_once(now=NOW) == []

    clinic.reopened = True
    [matched] = await watcher.check_once(now=NOW)

    assert matched.status == "matched"
    assert matched.matched_slot is not None
    assert isinstance(matched.draft_action, BookAction)
    assert matched.draft_action.patient_id == PATIENT_ID
    assert matched.draft_action.slot == matched.matched_slot.start


async def test_reopened_slot_can_draft_a_reschedule(tmp_path: Path) -> None:
    store = RebookingStore(tmp_path / "rebooking.sqlite3")
    request = analyze_call(_reschedule_events())
    assert request is not None
    assert request.intent == "reschedule"
    assert request.appointment_id == "A0001"
    store.add(request)
    clinic = ReopeningClinic()
    clinic.reopened = True

    [matched] = await RebookingWatcher(clinic, store).check_once(now=NOW)

    assert isinstance(matched.draft_action, RescheduleAction)
    assert matched.draft_action.appointment_id == "A0001"
    assert matched.draft_action.provider_id == "PR01"


async def test_a_window_that_ended_today_is_never_queried_again(tmp_path: Path) -> None:
    store = RebookingStore(tmp_path / "rebooking.sqlite3")
    request = analyze_call(_book_events())
    assert request is not None
    store.add(request)
    clinic = RecordingClinic()

    matched = await RebookingWatcher(clinic, store).check_once(
        now=datetime(2026, 9, 19, 9, 0, tzinfo=MADRID)
    )

    assert matched == []
    assert clinic.windows == []


async def test_the_queried_window_starts_the_day_after_the_check(tmp_path: Path) -> None:
    store = RebookingStore(tmp_path / "rebooking.sqlite3")
    events = _book_events()
    events[3]["args"] |= {"date_from": "2026-09-16", "date_to": "2026-09-20"}
    request = analyze_call(events)
    assert request is not None
    store.add(request)
    clinic = RecordingClinic()

    [matched] = await RebookingWatcher(clinic, store).check_once(now=NOW)

    assert clinic.windows == [(date(2026, 9, 19), date(2026, 9, 20))]
    assert matched.matched_slot is not None
    assert matched.matched_slot.start.astimezone(MADRID).date() > NOW.date()


async def test_a_rejected_query_does_not_abort_the_rest_of_the_batch(tmp_path: Path) -> None:
    store = RebookingStore(tmp_path / "rebooking.sqlite3")
    for events in (_book_events(), _reschedule_events()):
        request = analyze_call(events)
        assert request is not None
        store.add(request)
    clinic = FlakyClinic(ClinicApiError(422, "date range is outside the published calendar"))

    matched = await RebookingWatcher(clinic, store).check_once(now=NOW)

    assert clinic.calls == 2
    assert len(matched) == 1
    assert len(store.pending()) == 1


async def test_a_transport_failure_leaves_the_row_pending(tmp_path: Path) -> None:
    store = RebookingStore(tmp_path / "rebooking.sqlite3")
    request = analyze_call(_book_events())
    assert request is not None
    store.add(request)
    clinic = FlakyClinic(httpx.ConnectError("clinic unreachable"))

    assert await RebookingWatcher(clinic, store).check_once(now=NOW) == []
    assert [row.request_id for row in store.pending()] == [request.request_id]


async def test_the_time_range_is_read_in_madrid_whatever_offset_the_slot_carries(
    tmp_path: Path,
) -> None:
    store = RebookingStore(tmp_path / "rebooking.sqlite3")
    events = _book_events()
    events[3]["args"] |= {"time_from": "10:00", "time_to": "11:00"}
    request = analyze_call(events)
    assert request is not None
    assert request.time_from == time(10, 0)
    store.add(request)

    [matched] = await RebookingWatcher(UtcClinic(), store).check_once(now=NOW)

    assert matched.matched_slot is not None
    assert matched.matched_slot.start.utcoffset() == timedelta(0)
    assert time(10, 0) <= matched.matched_slot.start.astimezone(MADRID).time() < time(11, 0)
