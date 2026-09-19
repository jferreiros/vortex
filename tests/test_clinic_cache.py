"""Regression coverage for the in-process clinic snapshots."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path

import pytest

from vortex.clinic.client import ClinicClient, FakeClinicClient
from vortex.contract import (
    MADRID,
    AvailabilityResponse,
    BookAction,
    CancelAction,
    PrepareBookingInput,
    RescheduleAction,
    SubmitInput,
    SubmitResult,
    ToolContext,
)
from vortex.diary.tools import prepare_booking
from vortex.line.submit import submit_action
from vortex.observability.calllog import CallLog


class CountingFakeClinic(FakeClinicClient):
    def __init__(self) -> None:
        super().__init__()
        self.directory_fetches = 0
        self.availability_fetches = 0

    async def _fetch_directory(self, *args, **kwargs):
        self.directory_fetches += 1
        return await super()._fetch_directory(*args, **kwargs)

    async def _fetch_availability(self, **kwargs):
        self.availability_fetches += 1
        return await super()._fetch_availability(**kwargs)


class CountingLiveClinic(ClinicClient):
    def __init__(self) -> None:
        super().__init__("http://unused", "test-key")
        self.availability_fetches = 0

    async def _fetch_availability(self, *args, **kwargs):
        self.availability_fetches += 1
        await asyncio.sleep(0)
        return await FakeClinicClient().availability(**kwargs)


class BlockingLiveClinic(ClinicClient):
    """A live client whose fetch parks until the test releases it."""

    def __init__(self) -> None:
        super().__init__("http://unused", "test-key")
        self.availability_fetches = 0
        self.fetch_started = asyncio.Event()
        self.fetch_released = asyncio.Event()

    async def _fetch_availability(self, *args, **kwargs):
        self.availability_fetches += 1
        self.fetch_started.set()
        await self.fetch_released.wait()
        return AvailabilityResponse()


class BlockingFakeClinic(FakeClinicClient):
    """An offline client whose fetch parks until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.availability_fetches = 0
        self.fetch_started = asyncio.Event()
        self.fetch_released = asyncio.Event()

    async def _fetch_availability(self, **kwargs):
        self.availability_fetches += 1
        self.fetch_started.set()
        await self.fetch_released.wait()
        return await super()._fetch_availability(**kwargs)


class AcceptedSubmitter:
    async def submit(self, call_id, action):
        return SubmitResult(status="accepted")


class StaleSnapshotClinic(FakeClinicClient):
    async def fresh_availability(self, **query):
        return AvailabilityResponse()


NOW = datetime(2026, 9, 18, 10, 30, tzinfo=MADRID)


def _context(tmp_path: Path, clinic) -> ToolContext:
    return ToolContext(
        call_id="CA-cache",
        now=NOW,
        from_number="+34612345678",
        clinic=clinic,
        log=CallLog("CA-cache", tmp_path / "calls.jsonl"),
        submitter=AcceptedSubmitter(),
    )


async def test_directory_cache_normalizes_equivalent_phone_queries() -> None:
    clinic = CountingFakeClinic()

    first = await clinic.directory(phone="+34 612 345 678")
    second = await clinic.directory(phone="612345678")

    assert [p.patient_id for p in first] == [p.patient_id for p in second]
    assert clinic.directory_fetches == 1


async def test_availability_cache_hits_and_returns_isolated_models() -> None:
    clinic = CountingFakeClinic()
    query = {
        "date_from": date(2026, 9, 19),
        "date_to": date(2026, 9, 19),
        "specialty_id": "general_practice",
        "patient_id": "P00042",
    }

    first = await clinic.availability(**query)
    first.slots.clear()
    second = await clinic.availability(**query)

    assert second.slots
    assert clinic.availability_fetches == 1


async def test_live_availability_misses_are_deduplicated() -> None:
    clinic = CountingLiveClinic()
    query = {
        "date_from": date(2026, 9, 19),
        "date_to": date(2026, 9, 19),
        "specialty_id": "general_practice",
        "patient_id": "P00042",
    }

    await asyncio.gather(*(clinic.availability(**query) for _ in range(8)))

    assert clinic.availability_fetches == 1
    await clinic.aclose()


async def test_invalidation_during_a_live_miss_drops_the_stale_response() -> None:
    clinic = BlockingLiveClinic()
    query = {
        "date_from": date(2026, 9, 19),
        "date_to": date(2026, 9, 19),
        "specialty_id": "general_practice",
        "patient_id": "P00042",
    }

    pending = asyncio.create_task(clinic.availability(**query))
    await clinic.fetch_started.wait()
    clinic.invalidate_availability()
    clinic.fetch_released.set()
    await pending
    await clinic.availability(**query)

    assert clinic.availability_fetches == 2
    await clinic.aclose()


async def test_invalidation_during_a_fresh_fetch_drops_the_stale_response() -> None:
    clinic = BlockingLiveClinic()
    query = {
        "date_from": date(2026, 9, 19),
        "date_to": date(2026, 9, 19),
        "specialty_id": "general_practice",
        "patient_id": "P00042",
    }

    pending = asyncio.create_task(clinic.fresh_availability(**query))
    await clinic.fetch_started.wait()
    clinic.invalidate_availability()
    clinic.fetch_released.set()
    await pending
    await clinic.availability(**query)

    assert clinic.availability_fetches == 2
    await clinic.aclose()


async def test_invalidation_during_an_offline_miss_drops_the_stale_response() -> None:
    clinic = BlockingFakeClinic()
    query = {
        "date_from": date(2026, 9, 19),
        "date_to": date(2026, 9, 19),
        "specialty_id": "general_practice",
        "patient_id": "P00042",
    }

    pending = asyncio.create_task(clinic.availability(**query))
    await clinic.fetch_started.wait()
    clinic.invalidate_availability()
    clinic.fetch_released.set()
    await pending
    await clinic.availability(**query)

    assert clinic.availability_fetches == 2


@pytest.mark.parametrize(
    "action",
    [
        BookAction(
            patient_id="P00042",
            provider_id="PR01",
            location_id="centro",
            appointment_type_id="review",
            slot=datetime(2026, 9, 19, 9, 0, tzinfo=MADRID),
            policy_id="sanitas",
        ),
        CancelAction(appointment_id="A0001"),
        RescheduleAction(
            appointment_id="A0001",
            provider_id="PR01",
            location_id="centro",
            slot=datetime(2026, 9, 19, 9, 0, tzinfo=MADRID),
            policy_id="sanitas",
        ),
    ],
)
async def test_accepted_diary_writes_invalidate_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action
) -> None:
    # This accepted book/cancel/reschedule also fires database/hooks.py's
    # persist_submission (vortex/line/submit.py) — keep its writes in
    # tmp_path, never the repo's real database/.
    from vortex import settings as settings_module

    monkeypatch.setenv("VORTEX_PRODUCT_DB", str(tmp_path / "vortex_product.db"))
    settings_module.reset_settings()

    clinic = CountingFakeClinic()
    query = {
        "date_from": date(2026, 9, 19),
        "date_to": date(2026, 9, 19),
        "specialty_id": "general_practice",
        "patient_id": "P00042",
    }
    await clinic.availability(**query)
    await submit_action(_context(tmp_path, clinic), SubmitInput(action=action))
    await clinic.availability(**query)

    assert clinic.availability_fetches == 2
    settings_module.reset_settings()


async def test_prepare_booking_rechecks_outside_the_snapshot(tmp_path: Path) -> None:
    clinic = StaleSnapshotClinic()
    offered = await FakeClinicClient().availability(
        date_from=date(2026, 9, 19),
        date_to=date(2026, 9, 19),
        specialty_id="general_practice",
        patient_id="P00042",
    )
    result = await prepare_booking(
        _context(tmp_path, clinic),
        PrepareBookingInput(patient_id="P00042", slot=offered.slots[0], policy_id="sanitas"),
    )

    assert result.action is None
    assert result.rejection is not None
    assert result.rejection.reason == "no_availability"
