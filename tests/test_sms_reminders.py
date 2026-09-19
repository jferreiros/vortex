"""Day-before SMS reminder store and worker."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from vortex.contract import MADRID
from vortex.line.sms import DryRunSmsClient
from vortex.line.sms_reminders import (
    ReminderStore,
    ReminderWorker,
    build_book_reminder,
    cancel_book_reminders,
    reminder_text,
    schedule_book_reminder,
)
from vortex.settings import get_settings, reset_settings

WHEN = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)
NOW = datetime(2026, 9, 20, 10, 0, tzinfo=MADRID)


def test_reminder_text_includes_slot_and_names() -> None:
    body = reminder_text(when=WHEN, provider_name="Dra. Ruiz", location_name="Centro")
    assert "Recordatorio" in body
    assert "Dra. Ruiz" in body
    assert "Centro" in body
    assert "jueves 24 de septiembre a las 16:30" in body


def test_build_skips_when_inside_lead_window() -> None:
    reminder = build_book_reminder(
        to="+34662046392",
        when=WHEN,
        now=WHEN - timedelta(hours=12),
        lead=timedelta(hours=24),
    )
    assert reminder is None


def test_no_reminder_when_booked_within_24h() -> None:
    # Product rule: booked less than 24 h before the slot -> no reminder SMS,
    # even with a tiny demo lead that would otherwise fire immediately.
    booked_just_now = WHEN - timedelta(hours=23, minutes=59)
    assert (
        build_book_reminder(
            to="+34662046392",
            when=WHEN,
            now=booked_just_now,
            lead=timedelta(seconds=36),
        )
        is None
    )


def test_build_schedules_one_day_before() -> None:
    reminder = build_book_reminder(
        to="+34662046392",
        when=WHEN,
        now=NOW,
        lead=timedelta(hours=24),
    )
    assert reminder is not None
    assert reminder.to == "+34662046392"
    assert reminder.status == "pending"
    assert reminder.send_dt == WHEN - timedelta(days=1)


@pytest.mark.asyncio
async def test_store_add_and_cancel(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "reminders.json")
    reminder = await schedule_book_reminder(
        store,
        to="+34662046392",
        when=WHEN,
        now=NOW,
        provider_name="Dr. X",
    )
    assert reminder is not None
    assert store.path.exists()

    cancelled = await cancel_book_reminders(
        store,
        to="+34662046392",
        appointment_at=WHEN,
    )
    assert cancelled == 1
    rows = store._read()
    assert rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_worker_sends_due_reminder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORTEX_SMS_CONFIRMATIONS", "true")
    monkeypatch.setenv("VORTEX_SMS_DAY_BEFORE", "true")
    monkeypatch.setenv("VORTEX_SMS_REMINDERS_PATH", str(tmp_path / "reminders.json"))
    reset_settings()
    settings = get_settings()

    store = ReminderStore(tmp_path / "reminders.json")
    sms = DryRunSmsClient()
    # Lead already passed relative to NOW+ so claim_due will fire.
    await schedule_book_reminder(
        store,
        to="+34662046392",
        when=WHEN,
        now=NOW - timedelta(days=5),
        lead=timedelta(hours=24),
        provider_name="Dra. Ortiz",
        location_name="Arenal",
    )
    # Force send_at into the past by claiming at WHEN.
    worker = ReminderWorker(settings, store=store, sms=sms, poll_secs=60)
    sent = await worker.tick(WHEN)
    assert sent == 1
    assert len(sms.sent) == 1
    assert sms.sent[0][0] == "+34662046392"
    assert "Recordatorio" in sms.sent[0][1]
    rows = store._read()
    assert rows[0].status == "sent"


@pytest.mark.asyncio
async def test_worker_respects_force_to_via_scheduled_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The session stamps force_to onto the reminder ``to`` before scheduling."""
    monkeypatch.setenv("VORTEX_SMS_CONFIRMATIONS", "true")
    reset_settings()
    settings = get_settings()
    store = ReminderStore(tmp_path / "reminders.json")
    sms = DryRunSmsClient()
    await schedule_book_reminder(
        store,
        to="+34662046392",
        when=WHEN,
        now=NOW - timedelta(days=5),
    )
    worker = ReminderWorker(settings, store=store, sms=sms, poll_secs=60)
    await worker.tick(WHEN)
    assert sms.sent[0][0] == "+34662046392"
