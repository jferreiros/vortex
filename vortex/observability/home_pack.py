"""Real numbers for the Clinic View's Home page — no per-render mock. See
``business_insights.py`` for the sibling module the Insights page uses; this
one answers the Home page's four questions: how many calls, how many the
agent resolved on its own, when they land in the day, and how full the
diary already is.

Calls, resolution rate and volume come from ``synthetic-data/``.
``synthetic-data/logs/*.jsonl`` is CallLog-shaped exactly like a row of
``public.call_events`` (see ``synthetic-data/README.md``), so it goes through
the same ``view.build_calls`` pipeline the console uses for a real call, one
file at a time, concatenated. These fixture files are the only JSONL left:
real call events live in Postgres. ``probe:`` calls (tool-shape smoke tests,
empty ``from_number``, no real caller) are excluded from every count here —
they are not a patient call.

Occupancy is different: a call log never carries the capacity a booking was
made against, only the booking itself, so it can't be read the same way.
That number is precomputed straight off the clinic API's own GETs by
``scripts/precompute_wall_cache.py`` (run at every board start-up) into
``wall-cache/occupancy.json`` — see that script and ``wall-cache/README.md``
for how. This module just reads the file.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from vortex.observability.view import CallCard, build_calls
from vortex.settings import REPO_ROOT

MADRID = ZoneInfo("Europe/Madrid")

SYNTHETIC_LOG_DIR = REPO_ROOT / "synthetic-data" / "logs"

#: Business hours the hourly chart buckets into — the clinic's published
#: opening window, one bar per hour.
CHART_HOURS: tuple[int, ...] = tuple(range(9, 20))

#: Spanish display names for the specialty ids — the catalogue itself is in
#: English (it mirrors the platform's own field values). Site names need no
#: such map: "Arenal Centro" etc. are already proper nouns, identical in
#: both languages.
SPECIALTY_ES: dict[str, str] = {
    "general_practice": "Medicina general",
    "paediatrics": "Pediatría",
    "dermatology": "Dermatología",
    "orthopaedics": "Traumatología",
    "gynaecology": "Ginecología",
    "physiotherapy": "Fisioterapia",
}

DAY_LABEL_ES = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


# ---------------------------------------------------------------------------
# Loading the pack
# ---------------------------------------------------------------------------


def load_synthetic_cards() -> list[CallCard]:
    """Every real (non-probe) call in ``synthetic-data/logs/``, newest first."""
    events: list[dict[str, Any]] = []
    for path in sorted(SYNTHETIC_LOG_DIR.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    cards = build_calls(events)
    return [c for c in cards if not c.call_id.startswith("probe:")]


def _card_date(card: CallCard) -> date_cls | None:
    if not card.started_at:
        return None
    try:
        stamp = datetime.fromisoformat(card.started_at)
    except ValueError:
        return None
    return stamp.astimezone(MADRID).date() if stamp.tzinfo else stamp.date()


def _card_hour(card: CallCard) -> int | None:
    if not card.started_at:
        return None
    try:
        stamp = datetime.fromisoformat(card.started_at)
    except ValueError:
        return None
    local = stamp.astimezone(MADRID) if stamp.tzinfo else stamp
    return local.hour


def reference_date(cards: list[CallCard]) -> date_cls:
    """The pack has no wall clock of its own: "today" is the most recent
    calendar day any call actually landed on."""
    dates = [d for c in cards if (d := _card_date(c))]
    return max(dates) if dates else date_cls.today()


# ---------------------------------------------------------------------------
# 1. Headline stats
# ---------------------------------------------------------------------------


@dataclass
class HomeStats:
    calls_today: int = 0
    resolved_pct: float | None = None
    escalated_pct: float | None = None
    median_duration_s: float | None = None
    new_patients_registered: int = 0


def home_stats(cards: list[CallCard], today: date_cls) -> HomeStats:
    todays = [c for c in cards if _card_date(c) == today]
    stats = HomeStats(calls_today=len(todays))
    if not todays:
        return stats
    resolved = sum(
        1 for c in todays if c.status in {"booked", "registered", "rescheduled", "cancelled"}
    )
    escalated = sum(1 for c in todays if c.status == "escalated")
    stats.resolved_pct = round(100 * resolved / len(todays), 1)
    stats.escalated_pct = round(100 * escalated / len(todays), 1)
    stats.new_patients_registered = sum(1 for c in todays if c.action_kind == "register")
    durations = [c.duration_ms / 1000 for c in todays if c.duration_ms]
    if durations:
        stats.median_duration_s = median(durations)
    return stats


# ---------------------------------------------------------------------------
# 2. Hourly action volume (last 7 days, by the call's own clock)
# ---------------------------------------------------------------------------

#: How many days back "última semana" covers, today included.
HOURLY_WINDOW_DAYS = 7


def hourly_action_volume(cards: list[CallCard], today: date_cls) -> list[dict[str, Any]]:
    since = today - timedelta(days=HOURLY_WINDOW_DAYS - 1)
    booking: Counter[int] = Counter()
    reschedule: Counter[int] = Counter()
    cancel: Counter[int] = Counter()
    for card in cards:
        day = _card_date(card)
        if day is None or not (since <= day <= today):
            continue
        hour = _card_hour(card)
        if hour is None:
            continue
        if card.action_kind == "book":
            booking[hour] += 1
        elif card.action_kind == "reschedule":
            reschedule[hour] += 1
        elif card.action_kind == "cancel":
            cancel[hour] += 1
    return [
        {
            "hour": h,
            "booking": booking.get(h, 0),
            "reschedule": reschedule.get(h, 0),
            "cancel": cancel.get(h, 0),
        }
        for h in CHART_HOURS
    ]


# ---------------------------------------------------------------------------
# 3. Daily call volume trend, every day the pack has
# ---------------------------------------------------------------------------


def daily_call_volume(cards: list[CallCard]) -> list[dict[str, Any]]:
    counts: Counter[date_cls] = Counter()
    for card in cards:
        d = _card_date(card)
        if d:
            counts[d] += 1
    if not counts:
        return []
    days = sorted(counts)
    return [{"date": d.isoformat(), "total": counts[d]} for d in days]


# ---------------------------------------------------------------------------
# 4. Occupancy: read straight off wall-cache/occupancy.json
# ---------------------------------------------------------------------------
#
# Capacity and busy-slot counts are no longer computed here: they come
# precomputed from the clinic API's own GETs (GET /clinic once, GET
# /availability per specialty) by scripts/precompute_wall_cache.py, run at
# every board start-up (see live.py's main()) and by hand any other time.
# See wall-cache/README.md for the file shape and why occupancy needs a
# separate fetch+postprocess pass instead of a straight log read: a
# booking's payload names a provider and a slot, never the capacity it was
# booked against.

OCCUPANCY_CACHE_PATH = REPO_ROOT / "wall-cache" / "occupancy.json"

_occupancy_cache_value: dict[str, Any] | None = None


def _occupancy_cache() -> dict[str, Any]:
    """Loaded once per process — the file only changes across a board
    restart (or a manual rerun of the precompute script), never mid-run."""
    global _occupancy_cache_value
    if _occupancy_cache_value is None:
        try:
            _occupancy_cache_value = json.loads(OCCUPANCY_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _occupancy_cache_value = {}
    return _occupancy_cache_value


def _matching_cells(
    cells: list[dict[str, Any]], *, location_id: str, specialty_id: str
) -> list[dict[str, Any]]:
    return [
        c
        for c in cells
        if (not location_id or c["location_id"] == location_id)
        and (not specialty_id or c["specialty_id"] == specialty_id)
    ]


#: One 15-minute step, the unit ``scripts/precompute_wall_cache.py`` counts
#: capacity in, so a booked half-hour has to weigh two.
SLOT_MINUTES = 15


def _busy_from_database() -> dict[tuple[str, str, str], int]:
    """Booked 15-minute steps per (day, site, specialty), from the real diary.

    The cached ``busy_slots`` is only as real as the clinic client that built
    it, which offline is ``vortex/clinic/fixtures.py``. The product database
    holds what the line actually booked, so it is the better answer whenever
    it has rows — and the only one that reflects real traffic.

    Counted over distinct (provider, site, minute) steps rather than over
    appointments: several calls in this log booked the same opening, and a
    diary slot can only be taken once.
    """
    try:
        from database import db

        rows = db.list_appointments()
    except Exception:
        return {}

    steps: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        if not row.site_id or not row.specialty_id:
            continue
        try:
            start = datetime.fromisoformat(row.slot_start)
            end = datetime.fromisoformat(row.slot_end)
        except (TypeError, ValueError):
            continue
        local = start.astimezone(MADRID)
        minutes = max(SLOT_MINUTES, int((end - start).total_seconds() // 60))
        for offset in range(0, minutes, SLOT_MINUTES):
            step = local + timedelta(minutes=offset)
            steps.add(
                (
                    step.date().isoformat(),
                    row.site_id,
                    row.specialty_id,
                    row.provider_id or "",
                    step.isoformat(),
                )
            )

    busy: Counter[tuple[str, str, str]] = Counter()
    for day, site_id, specialty_id, _provider, _minute in steps:
        busy[(day, site_id, specialty_id)] += 1
    return dict(busy)


#: How long a diary read is reused. Unlike the occupancy file beside it, this
#: one is not fixed at start-up: the database gains rows while the board runs,
#: so caching it for the life of the process would freeze the Home page's
#: occupancy at whatever the diary held when the first tab opened.
BUSY_CACHE_TTL_S = 30.0

_busy_cache: dict[tuple[str, str, str], int] | None = None
_busy_cached_at = 0.0


def _database_busy() -> dict[tuple[str, str, str], int]:
    """The booked steps, re-read once every ``BUSY_CACHE_TTL_S``."""
    global _busy_cache, _busy_cached_at
    if _busy_cache is None or (time.monotonic() - _busy_cached_at) > BUSY_CACHE_TTL_S:
        _busy_cache = _busy_from_database()
        _busy_cached_at = time.monotonic()
    return _busy_cache


def _day_pct(
    by_date: dict[str, list[dict[str, Any]]], day: date_cls, *, location_id: str, specialty_id: str
) -> int:
    cells = _matching_cells(
        by_date.get(day.isoformat(), []), location_id=location_id, specialty_id=specialty_id
    )
    capacity = sum(c["capacity_slots"] for c in cells)
    if capacity <= 0:
        return 0
    # The larger of the two, never one replacing the other: the cached number
    # is capacity minus what /availability still offered, so it covers the
    # clinic's own seed bookings; the database covers what this line booked,
    # which the clinic (read-only) never learned about. Each is a floor the
    # other does not see, so a booking can only ever make a day fuller.
    real = _database_busy()
    busy = sum(
        max(c["busy_slots"], real.get((day.isoformat(), c["location_id"], c["specialty_id"]), 0))
        for c in cells
    )
    return max(0, min(100, round(100 * busy / capacity)))


def occupancy(*, site: str = "", specialty: str = "") -> dict[str, Any]:
    cache = _occupancy_cache()
    if not cache:
        return {"week": [], "weekAvgPct": 0, "monthPct": 0}

    site_name_to_id = {s["name"]: s["id"] for s in cache.get("sites", [])}
    specialty_name_to_id = {
        SPECIALTY_ES.get(s["id"], s["name"]): s["id"] for s in cache.get("specialties", [])
    }
    location_id = site_name_to_id.get(site, site)
    specialty_id = specialty_name_to_id.get(specialty, specialty)
    by_date = {d["date"]: d["cells"] for d in cache.get("days", [])}

    today = datetime.now(MADRID).date()
    week = []
    for i in range(7):
        day = today + timedelta(days=i)
        pct = _day_pct(by_date, day, location_id=location_id, specialty_id=specialty_id)
        week.append({"date": day.isoformat(), "label": DAY_LABEL_ES[day.weekday()], "pct": pct})
    week_avg = round(sum(d["pct"] for d in week) / len(week)) if week else 0

    month_days = [today + timedelta(days=i) for i in range(1, 31)]
    month_pcts = [
        _day_pct(by_date, d, location_id=location_id, specialty_id=specialty_id) for d in month_days
    ]
    month_pct = round(sum(month_pcts) / len(month_pcts)) if month_pcts else 0

    return {"week": week, "weekAvgPct": week_avg, "monthPct": month_pct}


def sites_catalogue() -> list[str]:
    return [s["name"] for s in _occupancy_cache().get("sites", [])]


def specialties_catalogue() -> list[str]:
    return [SPECIALTY_ES.get(s["id"], s["name"]) for s in _occupancy_cache().get("specialties", [])]


# ---------------------------------------------------------------------------
# Everything together
# ---------------------------------------------------------------------------


def home_overview(cards: list[CallCard] | None = None) -> dict[str, Any]:
    cards = cards if cards is not None else load_synthetic_cards()
    today = reference_date(cards)
    stats = home_stats(cards, today)
    return {
        "reference_date": today.isoformat(),
        "stats": {
            "calls_today": stats.calls_today,
            "resolved_pct": stats.resolved_pct,
            "escalated_pct": stats.escalated_pct,
            "median_duration_s": stats.median_duration_s,
            "new_patients_registered": stats.new_patients_registered,
        },
        "hourly_action_volume": hourly_action_volume(cards, today),
        "daily_call_volume": daily_call_volume(cards),
        "sites": sites_catalogue(),
        "specialties": specialties_catalogue(),
    }
