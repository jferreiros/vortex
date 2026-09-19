"""Day-before SMS reminders for accepted bookings.

When a book is accepted we queue a reminder for ``slot - lead`` (default one
day). A small background worker drains due rows and texts the caller (or
``sms_force_to``). Cancels drop matching pending rows so a cancelled
appointment is not reminded.

Persistence is a JSON file next to the calls log so a process restart does not
lose tomorrow's reminders. Failures never touch the submit path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from vortex.contract import MADRID
from vortex.line.sms import SmsClient, format_slot_es, make_sms_client
from vortex.settings import Settings

log = logging.getLogger("vortex.line.sms_reminders")

#: Product rule (Cristina, 2026-09-19): an appointment booked less than 24 h
#: before its slot gets no reminder SMS - the patient just booked it.
#: Hard-coded, not the lead: the lead is a demo knob, this rule is not.
MIN_BOOKING_GAP = timedelta(hours=24)

ReminderStatus = Literal["pending", "sent", "cancelled", "skipped"]


@dataclass
class Reminder:
    reminder_id: str
    to: str
    appointment_at: str  # ISO-8601 with offset
    send_at: str  # ISO-8601 with offset
    body: str
    patient_id: str = ""
    provider_id: str = ""
    location_id: str = ""
    appointment_id: str = ""
    status: ReminderStatus = "pending"
    detail: str = ""

    @property
    def appointment_dt(self) -> datetime:
        return datetime.fromisoformat(self.appointment_at)

    @property
    def send_dt(self) -> datetime:
        return datetime.fromisoformat(self.send_at)


def reminder_text(
    *,
    when: datetime,
    provider_name: str = "",
    location_name: str = "",
) -> str:
    stamp = format_slot_es(when)
    if provider_name and location_name:
        head = f"Recordatorio: mañana tienes cita con {provider_name} en {location_name}: {stamp}."
    elif provider_name:
        head = f"Recordatorio: mañana tienes cita con {provider_name}: {stamp}."
    elif location_name:
        head = f"Recordatorio: mañana tienes cita en {location_name}: {stamp}."
    else:
        head = f"Recordatorio: mañana tienes cita: {stamp}."
    return f"{head} Para cambios o cancelaciones, llama a la clínica."


def default_reminders_path(settings: Settings) -> Path:
    return settings.calls_log_path.with_name("sms_reminders.json")


class ReminderStore:
    """Tiny JSON list of reminders. One process, one lock."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()

    def _read(self) -> list[Reminder]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.exception("sms reminder store unreadable: %s", self.path)
            return []
        if not isinstance(raw, list):
            return []
        out: list[Reminder] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                out.append(Reminder(**row))
            except TypeError:
                continue
        return out

    def _write(self, rows: list[Reminder]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    async def add(self, reminder: Reminder) -> Reminder:
        async with self._lock:
            rows = self._read()
            rows = [
                row
                for row in rows
                if not (
                    row.status == "pending"
                    and row.to == reminder.to
                    and row.appointment_at == reminder.appointment_at
                )
            ]
            rows.append(reminder)
            self._write(rows)
            return reminder

    async def cancel_matching(
        self,
        *,
        to: str = "",
        appointment_at: str = "",
        appointment_id: str = "",
    ) -> int:
        async with self._lock:
            rows = self._read()
            cancelled = 0
            for row in rows:
                if row.status != "pending":
                    continue
                if appointment_id and row.appointment_id == appointment_id:
                    row.status = "cancelled"
                    row.detail = "cancelled_by_appointment_id"
                    cancelled += 1
                    continue
                if appointment_at and row.appointment_at == appointment_at:
                    if to and row.to != to:
                        continue
                    row.status = "cancelled"
                    row.detail = "cancelled_by_slot"
                    cancelled += 1
            if cancelled:
                self._write(rows)
            return cancelled

    async def claim_due(self, now: datetime) -> list[Reminder]:
        """Flip due pending rows to ``sent`` so two polls cannot double-send."""
        async with self._lock:
            rows = self._read()
            due: list[Reminder] = []
            now_aware = now if now.tzinfo is not None else now.replace(tzinfo=MADRID)
            for row in rows:
                if row.status != "pending":
                    continue
                try:
                    send_at = row.send_dt
                except ValueError:
                    row.status = "skipped"
                    row.detail = "bad_send_at"
                    continue
                if send_at.tzinfo is None:
                    send_at = send_at.replace(tzinfo=MADRID)
                if send_at <= now_aware:
                    row.status = "sent"
                    row.detail = "claimed"
                    due.append(Reminder(**asdict(row)))
            if due:
                self._write(rows)
            return due

    async def update_detail(self, reminder_id: str, *, detail: str, status: ReminderStatus) -> None:
        async with self._lock:
            rows = self._read()
            for row in rows:
                if row.reminder_id == reminder_id:
                    row.detail = detail
                    row.status = status
                    break
            self._write(rows)


def build_book_reminder(
    *,
    to: str,
    when: datetime,
    provider_name: str = "",
    location_name: str = "",
    provider_id: str = "",
    location_id: str = "",
    patient_id: str = "",
    now: datetime | None = None,
    lead: timedelta | None = None,
) -> Reminder | None:
    """Return a pending reminder, or ``None`` when ``send_at`` is already past."""
    if when.tzinfo is None:
        raise ValueError(f"appointment datetime must carry an offset: {when.isoformat()}")
    clock = now or datetime.now(tz=MADRID)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=MADRID)
    if when - clock < MIN_BOOKING_GAP:
        return None
    gap = lead if lead is not None else timedelta(days=1)
    send_at = when - gap
    if send_at <= clock:
        return None
    return Reminder(
        reminder_id=uuid.uuid4().hex,
        to=to,
        appointment_at=when.isoformat(),
        send_at=send_at.isoformat(),
        body=reminder_text(
            when=when,
            provider_name=provider_name,
            location_name=location_name,
        ),
        patient_id=patient_id,
        provider_id=provider_id,
        location_id=location_id,
        status="pending",
    )


def reminder_store_from_settings(settings: Settings) -> ReminderStore:
    path = (
        Path(settings.sms_reminders_path)
        if settings.sms_reminders_path
        else default_reminders_path(settings)
    )
    return ReminderStore(path)


async def schedule_book_reminder(
    store: ReminderStore,
    *,
    to: str,
    when: datetime,
    provider_name: str = "",
    location_name: str = "",
    provider_id: str = "",
    location_id: str = "",
    patient_id: str = "",
    now: datetime | None = None,
    lead: timedelta | None = None,
) -> Reminder | None:
    reminder = build_book_reminder(
        to=to,
        when=when,
        provider_name=provider_name,
        location_name=location_name,
        provider_id=provider_id,
        location_id=location_id,
        patient_id=patient_id,
        now=now,
        lead=lead,
    )
    if reminder is None:
        return None
    return await store.add(reminder)


async def cancel_book_reminders(
    store: ReminderStore,
    *,
    to: str = "",
    appointment_at: datetime | None = None,
    appointment_id: str = "",
) -> int:
    return await store.cancel_matching(
        to=to,
        appointment_at=appointment_at.isoformat() if appointment_at is not None else "",
        appointment_id=appointment_id,
    )


class ReminderWorker:
    def __init__(
        self,
        settings: Settings,
        *,
        store: ReminderStore | None = None,
        sms: SmsClient | None = None,
        poll_secs: float | None = None,
    ):
        self.settings = settings
        self.store = store or reminder_store_from_settings(settings)
        self.sms = sms or make_sms_client(settings)
        self.poll_secs = (
            poll_secs if poll_secs is not None else float(settings.sms_reminder_poll_secs or 30.0)
        )
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="sms-reminder-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.sms.aclose()

    async def _run(self) -> None:
        log.info(
            "sms reminder worker on (%s), poll=%.1fs",
            self.store.path,
            self.poll_secs,
        )
        while not self._stop.is_set():
            try:
                await self.tick(datetime.now(tz=MADRID))
            except Exception:  # noqa: BLE001 - worker must keep looping
                log.exception("sms reminder tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_secs)
            except TimeoutError:
                continue

    async def tick(self, now: datetime) -> int:
        due = await self.store.claim_due(now)
        for row in due:
            try:
                result = await self.sms.send(to=row.to, body=row.body)
                ok = result.status in ("sent", "dry_run")
                await self.store.update_detail(
                    row.reminder_id,
                    detail=result.detail or result.status,
                    status="sent" if ok else "skipped",
                )
                log.info(
                    "sms reminder %s -> %s (%s)",
                    row.reminder_id,
                    result.status,
                    result.detail,
                )
            except Exception as exc:  # noqa: BLE001
                await self.store.update_detail(
                    row.reminder_id,
                    detail=repr(exc),
                    status="skipped",
                )
                log.exception("sms reminder %s failed", row.reminder_id)
        return len(due)


def reminder_worker_status(worker: ReminderWorker | None) -> dict[str, Any]:
    if worker is None:
        return {"sms_reminders_worker": False}
    return {
        "sms_reminders_worker": True,
        "sms_reminders_path": str(worker.store.path),
        "sms_reminder_poll_secs": worker.poll_secs,
    }
