"""Precompute the Home page's agenda occupancy straight off the clinic API's
own read-only GETs — ``GET /clinic`` once for the catalogue (providers,
their schedules, sites, specialties, closure days), then ``GET /availability``
per specialty over the whole bookable window, through the same
``vortex.clinic.make_clinic_client()`` every lane calls: live when
``PLATFORM_API_KEY`` is set, the offline fixtures otherwise. Writes
``wall-cache/occupancy.json`` (see ``wall-cache/README.md``).

Postprocessing, since the API never hands back "how full is this diary":
a provider's open minutes that day (from their schedule, zeroed out on a
leave day or a clinic closure day) is capacity, in 15-minute slots; what
``/availability`` actually offers is what capacity has *not* already been
booked, so ``busy = capacity - free``. This is the same shape
``vortex/observability/home_overview.py`` used to compute in-process from
``vortex/clinic/fixtures.py`` + ``synthetic-data/`` — moved here so the
number is now the live diary's own, not a fixture snapshot.

``database/scripts/refresh_slots.py`` is a sibling cache with a different
job: it fetches day-by-day because it also needs `blocked`'s per-day
precision. This script only needs slot *counts*, so it fetches in
<=14-day chunks (the API's own max span) — far fewer calls, and the
totals are identical either way (a slot list is just "what's free").

Run by hand:

    uv run python scripts/precompute_wall_cache.py

Run automatically on every ``make board`` start-up — see
``vortex/observability/live.py``'s ``main()`` — so the file is never more
than one process lifetime stale.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from vortex.clinic import make_clinic_client
from vortex.contract import ProviderRecord
from vortex.settings import REPO_ROOT, get_settings

OUT_DIR = REPO_ROOT / "wall-cache"
OUT_PATH = OUT_DIR / "occupancy.json"
SLOT_MINUTES = 15
#: The API's own max span for one /availability call (date_to - date_from,
#: inclusive of both ends is 14 days).
WINDOW_DAYS = 14


def _open_minutes(provider: ProviderRecord, location_id: str, day: date) -> int:
    if any(lv.date_from <= day <= lv.date_to for lv in provider.leave):
        return 0
    total = 0
    for schedule in provider.schedules:
        if schedule.location_id != location_id:
            continue
        for hours in schedule.hours:
            if hours.weekday == day.weekday():
                opens = hours.opens.hour * 60 + hours.opens.minute
                closes = hours.closes.hour * 60 + hours.closes.minute
                total += max(0, closes - opens)
    return total


def _windows(start: date, end: date) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=WINDOW_DAYS - 1), end)
        out.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return out


async def build() -> dict[str, Any]:
    settings = get_settings()
    client = make_clinic_client(settings)
    try:
        catalogue = await client.catalogue()
        start = catalogue.bookable_from or date.today()
        end = catalogue.bookable_to or (start + timedelta(days=30))
        closure_days = set(catalogue.closure_days)
        location_ids = [loc.location_id for loc in catalogue.locations]

        capacity: dict[tuple[str, str, str], int] = {}
        day = start
        while day <= end:
            if day not in closure_days:
                for provider in catalogue.providers:
                    for location_id in location_ids:
                        minutes = _open_minutes(provider, location_id, day)
                        if minutes <= 0:
                            continue
                        key = (day.isoformat(), location_id, provider.specialty_id)
                        capacity[key] = capacity.get(key, 0) + minutes // SLOT_MINUTES
            day += timedelta(days=1)

        free: dict[tuple[str, str, str], int] = {}
        for specialty in catalogue.specialties:
            for window_start, window_end in _windows(start, end):
                response = await client.availability(
                    date_from=window_start, date_to=window_end, specialty_id=specialty.specialty_id
                )
                for slot in response.slots:
                    key = (slot.start.date().isoformat(), slot.location_id, specialty.specialty_id)
                    free[key] = free.get(key, 0) + 1

        by_day: dict[str, list[dict[str, Any]]] = {}
        for key in set(capacity) | set(free):
            day_key, location_id, specialty_id = key
            cap = capacity.get(key, 0)
            busy = max(0, cap - free.get(key, 0))
            by_day.setdefault(day_key, []).append(
                {
                    "location_id": location_id,
                    "specialty_id": specialty_id,
                    "capacity_slots": cap,
                    "busy_slots": busy,
                }
            )
        for cells in by_day.values():
            cells.sort(key=lambda c: (c["location_id"], c["specialty_id"]))

        return {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": "live" if settings.clinic_is_live else "fake",
            "bookable_from": start.isoformat(),
            "bookable_to": end.isoformat(),
            "sites": [{"id": loc.location_id, "name": loc.name} for loc in catalogue.locations],
            "specialties": [{"id": s.specialty_id, "name": s.name} for s in catalogue.specialties],
            "days": [{"date": d, "cells": by_day[d]} for d in sorted(by_day)],
        }
    finally:
        await client.aclose()


async def main_async() -> None:
    data = await build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total_cells = sum(len(d["cells"]) for d in data["days"])
    print(
        f"wrote {OUT_PATH.relative_to(REPO_ROOT)} — {len(data['days'])} days, "
        f"{total_cells} (location, specialty) cells, source={data['source']}"
    )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
