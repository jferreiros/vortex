"""What the ``/api/wall`` routers and the NiceGUI board pages both need.

This module is the data floor under both surfaces: the call feed, the card
cache every live screen redraws off, the diary catalogue/roster cache the
Agenda routes share, and the SSE envelope the two streams use.

It imports no page code on purpose. ``vortex.api.*`` modules import from
here; ``vortex.observability.live`` imports from here too and re-exports the
names its pages already call by their old private spelling. Nothing in
``vortex.api`` may import ``live``, or the board cannot start.

Every persistent read below goes to Postgres through ``database/db.py``.
There is no local file store: a missing Supabase configuration reads as
empty, and a write raises ``RuntimeError`` (the routers turn that into 503).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import StreamingResponse

from vortex.clinic.client import FakeClinicClient
from vortex.observability import calendar as cal
from vortex.observability import callfeed
from vortex.observability.view import CallCard, build_calls
from vortex.observability.wall_timeline import build_timeline, call_summary, latest_intent
from vortex.settings import get_settings

log = logging.getLogger("vortex.api")

MADRID = ZoneInfo("Europe/Madrid")

#: A call with no event for this long is over, whatever the log says.
STALE_AFTER_S = 180


# ---------------------------------------------------------------------------
# The call feed
# ---------------------------------------------------------------------------


def load_events(
    scope: str = "recent",
    *,
    since: datetime | None = None,
    cache_ttl: float = 0.0,
    max_calls: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict]:
    """The events a screen draws, and where they came from.

    One hop to ``callfeed``, which reads ``call_events`` in Supabase. Kept
    as a function rather than a re-export so every caller shares one place
    to look when the feed's arguments move.
    """
    return callfeed.load_events(scope, since=since, cache_ttl=cache_ttl, max_calls=max_calls)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def is_live(card: CallCard) -> bool:
    if not card.live:
        return False
    last = parse_ts(card.last_ts)
    if last is None:
        return True
    return (datetime.now(UTC) - last).total_seconds() < STALE_AFTER_S


def card_started(card: CallCard) -> datetime | None:
    if not card.started_at:
        return None
    try:
        stamp = datetime.fromisoformat(card.started_at)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def build_cards() -> tuple[list[CallCard], dict[str, Any] | None]:
    events, health, _source_info = load_events("recent")
    cards = build_calls(events)
    for card in cards:
        if card.live and not is_live(card):
            card.ended = True
            card.reason = card.reason or "stale"
    return cards, health


#: (monotonic stamp, cards, health). One load feeds every open tab and every
#: API poll. There is one feed now — the hosted ``call_events`` table — so
#: the cache no longer keys on a log path.
_cards_cache: tuple[float, list[CallCard], dict[str, Any] | None] | None = None
_cards_task: asyncio.Task[tuple[list[CallCard], dict[str, Any] | None]] | None = None
#: A redraw ticks about twice a second, so a load older than this is worth
#: repeating and anything newer is what the previous tick already read.
CARDS_TTL_S = 0.5


def _fresh_cards() -> tuple[list[CallCard], dict[str, Any] | None] | None:
    cached = _cards_cache
    if cached is None or time.monotonic() - cached[0] > CARDS_TTL_S:
        return None
    return cached[1], cached[2]


def load_cards() -> tuple[list[CallCard], dict[str, Any] | None]:
    """The cards, for a page being built. Blocks; call it once per render."""
    global _cards_cache
    fresh = _fresh_cards()
    if fresh is not None:
        return fresh
    cards, health = build_cards()
    _cards_cache = (time.monotonic(), cards, health)
    return cards, health


async def load_cards_async() -> tuple[list[CallCard], dict[str, Any] | None]:
    """The same cards for a redraw: one load per TTL for the whole board, in a
    worker thread. ``build_cards`` is a network read, and a redraw runs on the
    event loop with every other client's redraw."""
    global _cards_cache, _cards_task
    fresh = _fresh_cards()
    if fresh is not None:
        return fresh
    task = _cards_task
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.create_task(asyncio.to_thread(build_cards))
        _cards_task = task
    cards, health = await task
    _cards_cache = (time.monotonic(), cards, health)
    return cards, health


# ---------------------------------------------------------------------------
# Formatting the two API payloads share with the pages
# ---------------------------------------------------------------------------


def clock(value: str | None) -> str:
    stamp = parse_ts(value)
    if stamp is None:
        return "—"
    return stamp.astimezone(MADRID).strftime("%H:%M:%S")


def duration(card: CallCard) -> str:
    if card.duration_ms:
        secs = card.duration_ms / 1000
    else:
        start = parse_ts(card.started_at)
        end = datetime.now(UTC) if card.live else parse_ts(card.last_ts)
        if start is None or end is None:
            return "—"
        secs = max((end - start).total_seconds(), 0)
    return f"{int(secs // 60)}:{int(secs % 60):02d}"


# ---------------------------------------------------------------------------
# Server-Sent Events
# ---------------------------------------------------------------------------

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_response(request: Request, build, *, once: bool = False) -> StreamingResponse:
    """Push a JSON blob whenever ``build()`` changes; comment-ping otherwise.

    ``once`` sends a single data frame and closes — used by tests so the
    httpx client does not hang on an infinite stream.
    """

    async def gen():
        last = ""
        while True:
            if await request.is_disconnected():
                break
            payload = json.dumps(await asyncio.to_thread(build), ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
                if once:
                    break
            else:
                yield ": ping\n\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


def timeline_payload(call_id: str) -> dict[str, Any]:
    events, health, _source_info = load_events("recent")
    call = call_summary(events, call_id)
    call["submit_window_secs"] = get_settings().submit_window_secs
    return {
        "call_id": call_id,
        "items": build_timeline(events, call_id),
        "intent": latest_intent(events, call_id),
        "call": call,
        "line_up": health is not None,
    }


# ---------------------------------------------------------------------------
# The diary: catalogue, roster, bookings
# ---------------------------------------------------------------------------


def sync_clinic(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise RuntimeError("clinic client did not complete synchronously")


def sync_catalogue() -> Any:
    return sync_clinic(FakeClinicClient().catalogue())


#: How far back to read the log for the roster. Wider than the Home window
#: because a provider record is a lasting fact about the clinic, so an older
#: call that happened to look one up is still the best source for it.
AGENDA_ROSTER_DAYS = 30

AGENDA_CATALOGUE = None
AGENDA_PATIENTS: dict[str, Any] | None = None
AGENDA_BOOKINGS: dict[Any, Any] | None = None


def ensure_agenda() -> None:
    """Load catalogue, directory and appointments through the clinic client."""
    global AGENDA_CATALOGUE, AGENDA_PATIENTS
    if AGENDA_CATALOGUE is not None and AGENDA_PATIENTS is not None:
        return
    from datetime import timedelta

    pack = cal.SYNTHETIC_DATA_DIR
    data_dir = pack if (pack / "patients.json").exists() else None
    pack_client = FakeClinicClient(data_dir=data_dir) if data_dir is not None else None
    api_client = FakeClinicClient()
    AGENDA_CATALOGUE = sync_clinic(api_client.catalogue())
    # Offline that catalogue is fixtures, which know seven of the clinic's
    # twelve doctors. The call log carries the platform's own records for the
    # rest, so fold them in before any grid is built off it.
    events, _health, _source = load_events(
        f"agenda:{AGENDA_ROSTER_DAYS}",
        since=datetime.now(UTC) - timedelta(days=AGENDA_ROSTER_DAYS),
        cache_ttl=callfeed.INSIGHTS_CACHE_TTL_S,
    )
    AGENDA_CATALOGUE = cal.catalogue_with_log_roster(AGENDA_CATALOGUE, events)
    records = sync_clinic((pack_client or api_client).directory())
    seen = {row.patient_id for row in records}
    for row in sync_clinic(api_client.directory()):
        if row.patient_id not in seen:
            records.append(row)
            seen.add(row.patient_id)
    AGENDA_PATIENTS = cal.patient_index_from_records(records)
    # Bookings are deliberately not loaded here: they are the one part of the
    # agenda that changes while the board runs, and ``agenda_bookings_live``
    # owns them on its own TTL.
    # Real callers are not in the offline directory, so their visits would show
    # an id where a name belongs. The database carries whatever name the call
    # that booked them established; the directory still wins where it knows.
    rows, _call_ids = cal.load_database_agenda()
    for patient_id, brief in cal.patient_index_from_rows(rows).items():
        AGENDA_PATIENTS.setdefault(patient_id, brief)


def agenda_catalogue() -> Any:
    ensure_agenda()
    return AGENDA_CATALOGUE


def agenda_patients() -> dict[str, Any]:
    ensure_agenda()
    return AGENDA_PATIENTS or {}


def wall_cancelled_keys() -> set[cal.BookingKey]:
    """The slots the control centre cancelled by hand, as diary keys."""
    from database import db

    keys: set[cal.BookingKey] = set()
    try:
        rows = db.list_wall_cancellations()
    except Exception:
        # An unreachable store must never blank the diary.
        log.warning("wall_cancellations read failed; agenda shows every slot")
        return keys
    for row in rows:
        key = cal.cancel_key(row.provider_id, row.site_id, row.slot_start)
        if key is not None:
            keys.add(key)
    # Offline board: with no Supabase the cancel API writes to the local file
    # store instead (remote reads then return empty rather than raising), so
    # merge whichever local rows exist. Empty when Supabase serves cancels.
    from database import local_wall

    for row in local_wall.list_all():
        key = cal.cancel_key(
            row.get("provider_id"), row.get("site_id"), row.get("slot_start")
        )
        if key is not None:
            keys.add(key)
    return keys


#: How long a diary read is reused. The catalogue and the roster beside it
#: stay cached for the process — a provider's schedule is not what changes —
#: but the bookings are a database read, and the database gains rows while the
#: board runs. Caching those for the process life would leave the Agenda
#: showing whatever the diary held when the first tab opened.
AGENDA_BOOKINGS_TTL_S = 30.0

_AGENDA_BOOKINGS_AT = 0.0


def agenda_bookings_live() -> dict[cal.BookingKey, cal.Booking]:
    """The current bookings minus the slots the wall already cancelled."""
    global AGENDA_BOOKINGS, _AGENDA_BOOKINGS_AT
    ensure_agenda()
    stale = (time.monotonic() - _AGENDA_BOOKINGS_AT) > AGENDA_BOOKINGS_TTL_S
    if AGENDA_BOOKINGS is None or stale:
        AGENDA_BOOKINGS = cal.load_agenda_bookings(AGENDA_CATALOGUE)
        _AGENDA_BOOKINGS_AT = time.monotonic()
    return cal.drop_cancelled(AGENDA_BOOKINGS or {}, wall_cancelled_keys())
