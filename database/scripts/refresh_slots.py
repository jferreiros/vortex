"""Rebuild the auxiliary slots-by-specialty structure under database/processed/.

Fetches the whole bookable window **day by day** for every specialty, plus
the static provider -> specialty map from the catalogue, and writes two
JSON files:

    database/processed/slots_by_specialty.json   {specialty_id: [slot, ...]},
                                                  plus blocked_by_specialty
    database/processed/provider_specialty.json   {provider_id: specialty_id}

Day-by-day, not <=14-day chunks, and this matters: confirmed against the
live API that `blocked` only lists a provider when they're blocked for the
*entire* requested window, not a partial overlap. A 14-day chunk silently
missed Dr. Requena's real 14-30 Sept leave (no chunk boundary happened to
land exactly on his leave dates) - only asking one day at a time gets this
right. Slots aren't affected by this (a slot list is just "what's free"),
but since one call returns both, day-by-day for slots too avoids fetching
everything twice. ~40 specialties x days = a few hundred calls, still quick.

blocked_by_specialty is fetched with no patient_id/insurer (this is a
specialty-wide structure, not a per-patient one), so it only ever reflects
provider_on_leave / location_hours / type_not_offered - schedule facts, true
regardless of who's asking. The 8 insurance/referral/age DeclineReasons are
per-(patient, insurer) and cannot be precomputed here; check_eligibility
still needs a live, patient-and-insurer-scoped call for those.

Why specialty is the top key and there's no separate provider- or
type-keyed structure: every provider belongs to exactly one specialty, so
"by provider" is a strict subset of "by specialty" - filtering an
already-small, already-sorted specialty bucket by provider_id is cheap and
needs no parallel index. appointment_type is never a query key on its own
(it follows the record, per the clinic docs), so it's left as a plain field
on each row rather than its own index.

Nothing else in the codebase reads these files yet - every existing tool
still calls the clinic API directly, unchanged. This is a standalone
auxiliary cache, not wired into any tool or lane.

    uv run python database/scripts/refresh_slots.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vortex.clinic import make_clinic_client  # noqa: E402
from vortex.settings import get_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = REPO_ROOT / "database" / "processed"
MAX_SPAN_DAYS = 13  # date_to - date_from; the API's max span is 14 days inclusive


def _days(start: date, end: date) -> list[date]:
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


async def build() -> dict[str, Any]:
    clinic = make_clinic_client(get_settings())
    try:
        catalogue = await clinic.catalogue()
        provider_specialty = {p.provider_id: p.specialty_id for p in catalogue.providers}

        bookable_from = catalogue.bookable_from or date.today() + timedelta(days=1)
        bookable_to = catalogue.bookable_to or bookable_from + timedelta(days=MAX_SPAN_DAYS)

        by_specialty: dict[str, list[dict[str, Any]]] = {}
        blocked_by_specialty: dict[str, list[dict[str, Any]]] = {}
        for specialty in catalogue.specialties:
            rows: list[dict[str, Any]] = []
            blocked_rows: list[dict[str, Any]] = []
            for day in _days(bookable_from, bookable_to):
                result = await clinic.availability(
                    date_from=day, date_to=day, specialty_id=specialty.specialty_id
                )
                rows.extend(slot.model_dump(mode="json") for slot in result.slots)
                blocked_rows.extend(
                    {**b.model_dump(mode="json"), "date": day.isoformat()} for b in result.blocked
                )
            rows.sort(key=lambda r: r["start"])
            by_specialty[specialty.specialty_id] = rows
            blocked_by_specialty[specialty.specialty_id] = blocked_rows
    finally:
        await clinic.aclose()

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "bookable_from": bookable_from.isoformat(),
        "bookable_to": bookable_to.isoformat(),
        "provider_specialty": provider_specialty,
        "by_specialty": by_specialty,
        "blocked_by_specialty": blocked_by_specialty,
    }


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    data = asyncio.run(build())

    (PROCESSED_DIR / "provider_specialty.json").write_text(
        json.dumps(
            {
                "generated_at": data["generated_at"],
                "provider_specialty": data["provider_specialty"],
            },
            indent=2,
        )
    )
    (PROCESSED_DIR / "slots_by_specialty.json").write_text(
        json.dumps(
            {
                "generated_at": data["generated_at"],
                "bookable_from": data["bookable_from"],
                "bookable_to": data["bookable_to"],
                "by_specialty": data["by_specialty"],
                "blocked_by_specialty": data["blocked_by_specialty"],
            },
            indent=2,
        )
    )

    total = sum(len(rows) for rows in data["by_specialty"].values())
    total_blocked = sum(len(rows) for rows in data["blocked_by_specialty"].values())
    print(
        f"wrote {len(data['provider_specialty'])} providers, {total} slot rows, "
        f"{total_blocked} blocked entries across {len(data['by_specialty'])} specialties "
        f"-> {PROCESSED_DIR.relative_to(REPO_ROOT)}"
    )


if __name__ == "__main__":
    main()
